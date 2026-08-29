"""Local hardware worker for hybrid cloud-local processing.
Run this on local hardware (PC, Mac, home server) to offload from cloud.
Communicates with cloud via authenticated API.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import psutil

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent))

from clipai_config import app_config as config, SecurityConfig

# NOTE: process_video must be implemented by the user for their specific pipeline
# Example: from your_processing_module import process_video
try:
    from pipeline_lib import process_video
except ImportError:
    process_video = None
    logging.warning("pipeline_lib not found - implement process_video for your pipeline")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("clipai.local_worker")


@dataclass
class WorkerConfig:
    """Local worker configuration."""
    cloud_url: str
    api_key: str
    worker_id: str
    max_concurrent_jobs: int = 1
    poll_interval: float = 5.0
    heartbeat_interval: float = 30.0
    max_memory_percent: float = 85.0
    max_cpu_percent: float = 90.0
    min_disk_gb: float = 5.0
    job_timeout: int = 3600  # 1 hour


@dataclass
class Job:
    """Job from cloud queue."""
    job_id: str
    input_path: str
    params: dict
    assigned_at: float = field(default_factory=time.time)


class ResourceMonitor:
    """Monitor system resources and enforce limits."""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self._lock = threading.Lock()

    def check_resources(self) -> tuple[bool, str]:
        """Check if system has resources for a new job."""
        # Memory
        mem = psutil.virtual_memory()
        if mem.percent > self.config.max_memory_percent:
            return False, f"Memory usage too high: {mem.percent:.1f}%"

        # CPU
        cpu = psutil.cpu_percent(interval=0.5)
        if cpu > self.config.max_cpu_percent:
            return False, f"CPU usage too high: {cpu:.1f}%"

        # Disk
        disk = psutil.disk_usage("/")
        free_gb = disk.free / (1024**3)
        if free_gb < self.config.min_disk_gb:
            return False, f"Disk space too low: {free_gb:.1f}GB free"

        return True, "OK"

    def get_stats(self) -> dict:
        """Get current resource stats."""
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.1)
        disk = psutil.disk_usage("/")
        return {
            "memory_percent": mem.percent,
            "memory_available_gb": mem.available / (1024**3),
            "cpu_percent": cpu,
            "disk_free_gb": disk.free / (1024**3),
            "disk_total_gb": disk.total / (1024**3),
        }


class CloudClient:
    """HTTP client for communicating with cloud API."""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.client = httpx.Client(
            base_url=config.cloud_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=60.0,
        )

    def register(self) -> bool:
        """Register this worker with the cloud."""
        try:
            resp = self.client.post("/api/v1/workers/register", json={
                "worker_id": self.config.worker_id,
                "capabilities": ["video_processing", "dubbing", "transcription"],
                "max_concurrent_jobs": self.config.max_concurrent_jobs,
            })
            resp.raise_for_status()
            logger.info("Registered with cloud: %s", resp.json())
            return True
        except httpx.HTTPError as e:
            logger.error("Failed to register with cloud: %s", e)
            return False

    def heartbeat(self, stats: dict, current_jobs: int) -> bool:
        """Send heartbeat with resource stats."""
        try:
            resp = self.client.post("/api/v1/workers/heartbeat", json={
                "worker_id": self.config.worker_id,
                "stats": stats,
                "current_jobs": current_jobs,
                "status": "healthy" if current_jobs < self.config.max_concurrent_jobs else "busy",
            })
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.warning("Heartbeat failed: %s", e)
            return False

    def fetch_job(self) -> Optional[Job]:
        """Fetch next job from cloud queue."""
        try:
            resp = self.client.post("/api/v1/workers/fetch-job", json={
                "worker_id": self.config.worker_id,
            })
            if resp.status_code == 204:
                return None  # No jobs available
            resp.raise_for_status()
            data = resp.json()
            return Job(
                job_id=data["job_id"],
                input_path=data["input_path"],
                params=data["params"],
            )
        except httpx.HTTPError as e:
            logger.warning("Fetch job failed: %s", e)
            return None

    def download_video(self, job_id: str, dest_path: Path) -> bool:
        """Download video file from cloud storage."""
        try:
            # For now, assume cloud provides a presigned URL or direct download
            resp = self.client.get(f"/api/v1/workers/jobs/{job_id}/download", follow_redirects=True)
            resp.raise_for_status()
            dest_path.write_bytes(resp.content)
            return True
        except httpx.HTTPError as e:
            logger.error("Download failed for job %s: %s", job_id, e)
            return False

    def upload_results(self, job_id: str, results_dir: Path) -> bool:
        """Upload processed clips to cloud."""
        try:
            files = []
            for clip_file in results_dir.glob("*.mp4"):
                files.append(("files", (clip_file.name, clip_file.open("rb"), "video/mp4")))

            manifest_file = results_dir / "manifest.json"
            if manifest_file.exists():
                files.append(("manifest", (manifest_file.name, manifest_file.open("rb"), "application/json")))

            resp = self.client.post(f"/api/v1/workers/jobs/{job_id}/upload", files=files)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.error("Upload failed for job %s: %s", job_id, e)
            return False
        finally:
            for _, (_, f, _) in files:
                f.close()

    def report_job_complete(self, job_id: str, success: bool, error: str = "") -> bool:
        """Report job completion to cloud."""
        try:
            resp = self.client.post("/api/v1/workers/jobs/complete", json={
                "worker_id": self.config.worker_id,
                "job_id": job_id,
                "success": success,
                "error": error,
            })
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.error("Report completion failed for job %s: %s", job_id, e)
            return False


class LocalWorker:
    """Main local worker process."""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.resource_monitor = ResourceMonitor(config)
        self.cloud = CloudClient(config)
        self.executor = ThreadPoolExecutor(max_workers=config.max_concurrent_jobs)
        self.current_jobs: Dict[str, Job] = {}
        self.jobs_lock = threading.Lock()
        self.running = False
        self._shutdown_event = threading.Event()

    def start(self) -> None:
        """Start the worker."""
        logger.info("Starting local worker %s", self.config.worker_id)

        # Register with cloud
        if not self.config.cloud_url.startswith("http"):
            logger.error("Invalid cloud URL: %s", self.config.cloud_url)
            return

        if not self.cloud.register():
            logger.error("Failed to register with cloud, exiting")
            return

        self.running = True

        # Start background threads
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        heartbeat_thread.start()

        # Wait for shutdown
        self._shutdown_event.wait()

    def stop(self) -> None:
        """Stop the worker gracefully."""
        logger.info("Stopping worker...")
        self.running = False
        self._shutdown_event.set()

        # Wait for current jobs to complete (with timeout)
        deadline = time.time() + 60
        while self.current_jobs and time.time() < deadline:
            time.sleep(1)

        self.executor.shutdown(wait=True, cancel_futures=True)
        logger.info("Worker stopped")

    def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self.running:
            time.sleep(self.config.heartbeat_interval)
            if not self.running:
                break

            stats = self.resource_monitor.get_stats()
            with self.jobs_lock:
                current = len(self.current_jobs)
            self.cloud.heartbeat(stats, current)

    def _poll_loop(self) -> None:
        """Poll for new jobs."""
        while self.running:
            # Check resources before fetching
            ok, reason = self.resource_monitor.check_resources()
            if not ok:
                logger.warning("Resources low, skipping poll: %s", reason)
                time.sleep(self.config.poll_interval * 2)
                continue

            with self.jobs_lock:
                if len(self.current_jobs) >= self.config.max_concurrent_jobs:
                    time.sleep(self.config.poll_interval)
                    continue

            job = self.cloud.fetch_job()
            if job:
                logger.info("Got job %s", job.job_id)
                self.executor.submit(self._process_job, job)
            else:
                time.sleep(self.config.poll_interval)

    def _process_job(self, job: Job) -> None:
        """Process a single job."""
        with self.jobs_lock:
            self.current_jobs[job.job_id] = job

        job_dir = Path("jobs") / job.job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Download video
            input_path = job_dir / "input.mp4"
            logger.info("Downloading video for job %s", job.job_id)
            if not self.cloud.download_video(job.job_id, input_path):
                raise RuntimeError("Failed to download video")

            # Process video
            logger.info("Processing job %s", job.job_id)
            if process_video is None:
                raise RuntimeError("process_video not implemented - add your video processing function")
            result = process_video(
                str(input_path),
                str(job_dir),
                n_clips=job.params.get("n_clips", 3),
                watermark=job.params.get("watermark", True),
                dub_lang=job.params.get("dub_lang"),
                clip_format=job.params.get("clip_format", "vertical"),
                caption_style=job.params.get("caption_style", "bold"),
            )

            # Upload results
            logger.info("Uploading results for job %s", job.job_id)
            if not self.cloud.upload_results(job.job_id, job_dir):
                raise RuntimeError("Failed to upload results")

            self.cloud.report_job_complete(job.job_id, True)
            logger.info("Job %s completed successfully", job.job_id)

        except Exception as e:
            logger.exception("Job %s failed: %s", job.job_id, e)
            self.cloud.report_job_complete(job.job_id, False, str(e))

        finally:
            with self.jobs_lock:
                self.current_jobs.pop(job.job_id, None)
            # Cleanup
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="ClipAI Local Worker")
    parser.add_argument("--cloud-url", required=True, help="Cloud API URL (e.g., https://api.yourdomain.com)")
    parser.add_argument("--api-key", required=True, help="Worker API key")
    parser.add_argument("--worker-id", default=None, help="Worker ID (auto-generated if not provided)")
    parser.add_argument("--max-jobs", type=int, default=1, help="Max concurrent jobs")
    parser.add_argument("--max-memory", type=float, default=85.0, help="Max memory %")
    parser.add_argument("--max-cpu", type=float, default=90.0, help="Max CPU %")
    parser.add_argument("--min-disk", type=float, default=5.0, help="Min disk GB")
    args = parser.parse_args()

    worker_id = args.worker_id or f"worker-{uuid.uuid4().hex[:8]}-{os.uname().nodename}"

    config = WorkerConfig(
        cloud_url=args.cloud_url.rstrip("/"),
        api_key=args.api_key,
        worker_id=worker_id,
        max_concurrent_jobs=args.max_jobs,
        max_memory_percent=args.max_memory,
        max_cpu_percent=args.max_cpu,
        min_disk_gb=args.min_disk,
    )

    worker = LocalWorker(config)

    # Handle signals
    def signal_handler(signum, frame):
        logger.info("Received signal %s", signum)
        worker.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        worker.start()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()