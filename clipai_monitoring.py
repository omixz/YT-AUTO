"""Resource monitoring, adaptive queue management, health checks, and circuit breakers."""
from __future__ import annotations

import logging
import threading
import time
import psutil
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional
from collections import deque

from clipai_config import app_config as config, SecurityConfig

logger = logging.getLogger("clipai.monitoring")


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class CircuitState(str, Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class ResourceSnapshot:
    """System resource snapshot."""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_available_gb: float
    disk_free_gb: float
    disk_total_gb: float
    network_io: Dict[str, int] = field(default_factory=dict)
    process_count: int = 0
    load_average: tuple = (0.0, 0.0, 0.0)


@dataclass
class ResourceLimits:
    """Resource limits for adaptive scaling."""
    max_cpu_percent: float = 85.0
    max_memory_percent: float = 85.0
    min_memory_gb: float = 1.0
    min_disk_gb: float = 5.0
    max_concurrent_jobs: int = 1
    target_queue_latency_seconds: float = 30.0


class ResourceMonitor:
    """Monitor system resources with history and alerting."""

    def __init__(self, limits: ResourceLimits = None, history_size: int = 300):
        self.limits = limits or ResourceLimits()
        self.history: deque = deque(maxlen=history_size)
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[ResourceSnapshot], None]] = []
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()
        self._last_net_io = psutil.net_io_counters()

    def start(self, interval: float = 10.0) -> None:
        """Start background monitoring."""
        self._stop_monitor.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, args=(interval,), daemon=True)
        self._monitor_thread.start()
        logger.info("Resource monitor started")

    def stop(self) -> None:
        """Stop background monitoring."""
        self._stop_monitor.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("Resource monitor stopped")

    def _monitor_loop(self, interval: float) -> None:
        while not self._stop_monitor.wait(interval):
            try:
                snapshot = self._take_snapshot()
                with self._lock:
                    self.history.append(snapshot)
                for callback in self._callbacks:
                    try:
                        callback(snapshot)
                    except Exception as e:
                        logger.error("Monitor callback failed: %s", e)
            except Exception as e:
                logger.error("Resource monitoring error: %s", e)

    def _take_snapshot(self) -> ResourceSnapshot:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        net_io = psutil.net_io_counters()
        net_delta = {}
        if self._last_net_io:
            net_delta = {
                "bytes_sent": net_io.bytes_sent - self._last_net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv - self._last_net_io.bytes_recv,
            }
        self._last_net_io = net_io

        try:
            load = psutil.getloadavg()
        except AttributeError:
            load = (0.0, 0.0, 0.0)  # Windows

        return ResourceSnapshot(
            timestamp=time.time(),
            cpu_percent=cpu,
            memory_percent=mem.percent,
            memory_available_gb=mem.available / (1024**3),
            disk_free_gb=disk.free / (1024**3),
            disk_total_gb=disk.total / (1024**3),
            network_io=net_delta,
            process_count=len(psutil.pids()),
            load_average=load,
        )

    def get_current(self) -> Optional[ResourceSnapshot]:
        with self._lock:
            return self.history[-1] if self.history else None

    def get_history(self, seconds: int = 60) -> List[ResourceSnapshot]:
        cutoff = time.time() - seconds
        with self._lock:
            return [s for s in self.history if s.timestamp > cutoff]

    def get_averages(self, seconds: int = 60) -> Dict[str, float]:
        history = self.get_history(seconds)
        if not history:
            return {}
        return {
            "cpu_percent": sum(s.cpu_percent for s in history) / len(history),
            "memory_percent": sum(s.memory_percent for s in history) / len(history),
            "memory_available_gb": sum(s.memory_available_gb for s in history) / len(history),
        }

    def is_healthy(self) -> tuple[bool, str]:
        """Check if resources are within limits."""
        snap = self.get_current()
        if not snap:
            return True, "No data yet"

        if snap.cpu_percent > self.limits.max_cpu_percent:
            return False, f"CPU {snap.cpu_percent:.1f}% > {self.limits.max_cpu_percent}%"
        if snap.memory_percent > self.limits.max_memory_percent:
            return False, f"Memory {snap.memory_percent:.1f}% > {self.limits.max_memory_percent}%"
        if snap.memory_available_gb < self.limits.min_memory_gb:
            return False, f"Available memory {snap.memory_available_gb:.1f}GB < {self.limits.min_memory_gb}GB"
        if snap.disk_free_gb < self.limits.min_disk_gb:
            return False, f"Disk free {snap.disk_free_gb:.1f}GB < {self.limits.min_disk_gb}GB"
        return True, "OK"

    def get_recommended_concurrency(self) -> int:
        """Calculate recommended concurrent jobs based on resources."""
        snap = self.get_current()
        if not snap:
            return self.limits.max_concurrent_jobs

        # Scale based on available memory (each job needs ~1-2GB)
        mem_jobs = max(1, int(snap.memory_available_gb / 1.5))
        cpu_jobs = max(1, int((100 - snap.cpu_percent) / 20))

        return min(self.limits.max_concurrent_jobs, mem_jobs, cpu_jobs)

    def add_callback(self, callback: Callable[[ResourceSnapshot], None]) -> None:
        self._callbacks.append(callback)


class CircuitBreaker:
    """Circuit breaker for external service calls."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: float = 60.0,
        excluded_exceptions: tuple = (),
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.excluded_exceptions = excluded_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._last_failure_time and time.time() - self._last_failure_time > self.timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    logger.info("Circuit breaker %s: OPEN -> HALF_OPEN", self.name)
            return self._state

    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(f"Circuit breaker {self.name} is OPEN")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.excluded_exceptions:
            raise
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    logger.info("Circuit breaker %s: HALF_OPEN -> CLOSED", self.name)

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("Circuit breaker %s: HALF_OPEN -> OPEN", self.name)
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning("Circuit breaker %s: CLOSED -> OPEN (failures: %d)",
                             self.name, self._failure_count)

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get_or_create(self, name: str, **kwargs) -> CircuitBreaker:
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, **kwargs)
            return self._breakers[name]

    def get_all_states(self) -> Dict[str, Dict]:
        with self._lock:
            return {
                name: {
                    "state": breaker.state.value,
                    "failure_count": breaker._failure_count,
                    "success_count": breaker._success_count,
                }
                for name, breaker in self._breakers.items()
            }

    def reset_all(self) -> None:
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()


class HealthChecker:
    """Comprehensive health checking for the application."""

    def __init__(self, resource_monitor: ResourceMonitor, circuit_breakers: CircuitBreakerRegistry):
        self.resource_monitor = resource_monitor
        self.circuit_breakers = circuit_breakers
        self._checks: Dict[str, Callable[[], tuple[bool, str]]] = {}
        self._last_results: Dict[str, tuple[HealthStatus, str]] = {}

    def register_check(self, name: str, check: Callable[[], tuple[bool, str]]) -> None:
        """Register a health check function."""
        self._checks[name] = check

    def run_checks(self) -> Dict[str, Dict]:
        """Run all health checks."""
        results = {}
        overall = HealthStatus.HEALTHY

        # Resource check
        healthy, msg = self.resource_monitor.is_healthy()
        status = HealthStatus.HEALTHY if healthy else HealthStatus.DEGRADED
        if not healthy:
            overall = HealthStatus.DEGRADED
        results["resources"] = {"status": status.value, "message": msg}
        self._last_results["resources"] = (status, msg)

        # Custom checks
        for name, check in self._checks.items():
            try:
                healthy, msg = check()
                status = HealthStatus.HEALTHY if healthy else HealthStatus.UNHEALTHY
                if not healthy and overall == HealthStatus.HEALTHY:
                    overall = HealthStatus.DEGRADED
            except Exception as e:
                status = HealthStatus.UNHEALTHY
                msg = f"Check failed: {e}"
                overall = HealthStatus.UNHEALTHY

            results[name] = {"status": status.value, "message": msg}
            self._last_results[name] = (status, msg)

        # Circuit breaker states
        cb_states = self.circuit_breakers.get_all_states()
        for name, state in cb_states.items():
            if state["state"] == CircuitState.OPEN.value:
                overall = HealthStatus.DEGRADED
            results[f"circuit_{name}"] = {"status": state["state"], "details": state}

        results["overall"] = overall.value
        return results

    def get_last_results(self) -> Dict[str, Dict]:
        return {
            name: {"status": status.value, "message": msg}
            for name, (status, msg) in self._last_results.items()
        }


class AdaptiveQueueManager:
    """Adaptively manage queue concurrency based on resources."""

    def __init__(
        self,
        resource_monitor: ResourceMonitor,
        queue_getter: Callable[[], int],  # Returns current queue depth
        worker_setter: Callable[[int], None],  # Sets max concurrent workers
    ):
        self.resource_monitor = resource_monitor
        self.queue_getter = queue_getter
        self.worker_setter = worker_setter
        self._lock = threading.Lock()
        self._enabled = True
        self._last_adjustment = 0
        self._adjustment_interval = 30  # seconds

    def adjust(self) -> None:
        """Adjust worker count based on current conditions."""
        if not self._enabled:
            return

        now = time.time()
        if now - self._last_adjustment < self._adjustment_interval:
            return

        with self._lock:
            recommended = self.resource_monitor.get_recommended_concurrency()
            queue_depth = self.queue_getter()

            # If queue is backing up but resources allow, increase
            if queue_depth > 5 and recommended > 1:
                recommended = min(recommended + 1, self.resource_monitor.limits.max_concurrent_jobs)

            self.worker_setter(recommended)
            self._last_adjustment = now
            logger.debug("Adjusted concurrency to %d (queue: %d)", recommended, queue_depth)

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False


# Global instances
resource_monitor = ResourceMonitor()
circuit_breakers = CircuitBreakerRegistry()
health_checker = HealthChecker(resource_monitor, circuit_breakers)


def init_monitoring() -> None:
    """Initialize monitoring with default checks."""
    # Register default circuit breakers
    circuit_breakers.get_or_create("whisper", failure_threshold=3, timeout=120)
    circuit_breakers.get_or_create("google_translate", failure_threshold=5, timeout=60)
    circuit_breakers.get_or_create("piper_tts", failure_threshold=3, timeout=120)
    circuit_breakers.get_or_create("stripe", failure_threshold=5, timeout=60)
    circuit_breakers.get_or_create("resend", failure_threshold=5, timeout=60)
    circuit_breakers.get_or_create("database", failure_threshold=3, timeout=30)

    # Register health checks
    def check_disk():
        disk = psutil.disk_usage("/")
        free_gb = disk.free / (1024**3)
        return free_gb > 1.0, f"Disk free: {free_gb:.1f}GB"

    def check_queue():
        # This would be implemented with actual queue reference
        return True, "Queue operational"

    health_checker.register_check("disk", check_disk)
    health_checker.register_check("queue", check_queue)

    resource_monitor.start()
    logger.info("Monitoring initialized")