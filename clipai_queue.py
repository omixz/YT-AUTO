"""Persistent job queue with SQLite backend and Redis support.
Provides durability across restarts and distributed worker coordination.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from clipai_config import app_config as config, sanitize_error_message

logger = logging.getLogger("clipai.queue")


class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(int, Enum):
    LOW = 0
    NORMAL = 50
    HIGH = 100
    CRITICAL = 200


@dataclass
class Job:
    """Persistent job record."""
    id: str
    user_id: str
    status: JobStatus
    priority: JobPriority = JobPriority.NORMAL
    input_path: str = ""
    params: Dict = None
    result: Dict = None
    error: str = ""
    created_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    worker_id: str = ""
    attempts: int = 0
    max_attempts: int = 3

    def __post_init__(self):
        if self.params is None:
            self.params = {}
        if self.result is None:
            self.result = {}
        if self.created_at == 0.0:
            self.created_at = time.time()


class QueueBackend:
    """Abstract queue backend."""

    def enqueue(self, job: Job) -> bool:
        raise NotImplementedError

    def dequeue(self, worker_id: str, max_jobs: int = 1) -> List[Job]:
        raise NotImplementedError

    def update_job(self, job: Job) -> bool:
        raise NotImplementedError

    def get_job(self, job_id: str) -> Optional[Job]:
        raise NotImplementedError

    def get_jobs_by_user(self, user_id: str, limit: int = 50) -> List[Job]:
        raise NotImplementedError

    def cleanup_old(self, max_age_seconds: int) -> int:
        raise NotImplementedError

    def get_stats(self) -> Dict:
        raise NotImplementedError


class SQLiteQueueBackend(QueueBackend):
    """SQLite-backed persistent queue."""

    def __init__(self, db_path: str = "queue.db"):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 50,
                    input_path TEXT NOT NULL,
                    params TEXT NOT NULL DEFAULT '{}',
                    result TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    started_at REAL NOT NULL DEFAULT 0,
                    completed_at REAL NOT NULL DEFAULT 0,
                    worker_id TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_priority ON jobs(status, priority DESC, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON jobs(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_worker_id ON jobs(worker_id)")

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            user_id=row["user_id"],
            status=JobStatus(row["status"]),
            priority=JobPriority(row["priority"]),
            input_path=row["input_path"],
            params=json.loads(row["params"]),
            result=json.loads(row["result"]),
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            worker_id=row["worker_id"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
        )

    def enqueue(self, job: Job) -> bool:
        with self._lock, self._get_conn() as conn:
            conn.execute("""
                INSERT INTO jobs (id, user_id, status, priority, input_path, params, result, error,
                                 created_at, started_at, completed_at, worker_id, attempts, max_attempts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.id, job.user_id, job.status.value, job.priority.value,
                job.input_path, json.dumps(job.params), json.dumps(job.result), job.error,
                job.created_at, job.started_at, job.completed_at,
                job.worker_id, job.attempts, job.max_attempts
            ))
        return True

    def dequeue(self, worker_id: str, max_jobs: int = 1) -> List[Job]:
        jobs = []
        with self._lock, self._get_conn() as conn:
            for _ in range(max_jobs):
                row = conn.execute("""
                    SELECT * FROM jobs
                    WHERE status = ? AND (worker_id = '' OR worker_id = ?)
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                """, (JobStatus.QUEUED.value, worker_id)).fetchone()

                if not row:
                    break

                job = self._row_to_job(row)
                job.status = JobStatus.PROCESSING
                job.worker_id = worker_id
                job.started_at = time.time()
                job.attempts += 1

                conn.execute("""
                    UPDATE jobs SET status = ?, worker_id = ?, started_at = ?, attempts = ?
                    WHERE id = ?
                """, (job.status.value, job.worker_id, job.started_at, job.attempts, job.id))

                jobs.append(job)
        return jobs

    def update_job(self, job: Job) -> bool:
        with self._lock, self._get_conn() as conn:
            conn.execute("""
                UPDATE jobs SET status = ?, result = ?, error = ?, completed_at = ?, attempts = ?
                WHERE id = ?
            """, (job.status.value, json.dumps(job.result), job.error, job.completed_at, job.attempts, job.id))
        return True

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock, self._get_conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_job(row) if row else None

    def get_jobs_by_user(self, user_id: str, limit: int = 50) -> List[Job]:
        with self._lock, self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
            """, (user_id, limit)).fetchall()
            return [self._row_to_job(r) for r in rows]

    def cleanup_old(self, max_age_seconds: int) -> int:
        cutoff = time.time() - max_age_seconds
        with self._lock, self._get_conn() as conn:
            # Delete completed/failed jobs older than cutoff
            cursor = conn.execute("""
                DELETE FROM jobs
                WHERE status IN (?, ?) AND completed_at > 0 AND completed_at < ?
            """, (JobStatus.COMPLETED.value, JobStatus.FAILED.value, cutoff))
            deleted = cursor.rowcount

            # Also clean up abandoned processing jobs (stuck > 2x max_age)
            stuck_cutoff = time.time() - (max_age_seconds * 2)
            cursor = conn.execute("""
                UPDATE jobs SET status = ?, error = ?, completed_at = ?
                WHERE status = ? AND started_at > 0 AND started_at < ?
            """, (JobStatus.FAILED.value, "Job abandoned (worker died)", time.time(), JobStatus.PROCESSING.value, stuck_cutoff))

        return deleted

    def get_stats(self) -> Dict:
        with self._lock, self._get_conn() as conn:
            stats = {}
            for status in JobStatus:
                count = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = ?", (status.value,)).fetchone()[0]
                stats[status.value] = count
            stats["total"] = sum(stats.values())
            return stats


class RedisQueueBackend(QueueBackend):
    """Redis-backed distributed queue (for multi-worker setups)."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        if not REDIS_AVAILABLE:
            raise RuntimeError("redis-py not installed. Run: pip install redis")
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self._queue_key = "clipai:queue:pending"
        self._jobs_key = "clipai:jobs"
        self._processing_key = "clipai:queue:processing"

    def enqueue(self, job: Job) -> bool:
        pipe = self.redis.pipeline()
        pipe.hset(self._jobs_key, job.id, json.dumps(asdict(job)))
        pipe.zadd(self._queue_key, {job.id: -job.priority.value * 1e12 + job.created_at})
        pipe.execute()
        return True

    def dequeue(self, worker_id: str, max_jobs: int = 1) -> List[Job]:
        jobs = []
        for _ in range(max_jobs):
            # Use Lua script for atomic dequeue
            lua_script = """
            local job_id = redis.call('ZPOPMIN', KEYS[1])
            if job_id then
                redis.call('ZADD', KEYS[2], ARGV[1], job_id[1])
                redis.call('HSET', KEYS[3], job_id[1] .. ':worker', ARGV[2])
                redis.call('HSET', KEYS[3], job_id[1] .. ':started_at', ARGV[1])
                redis.call('HINCRBY', KEYS[3], job_id[1] .. ':attempts', 1)
                return job_id[1]
            end
            return nil
            """
            script = self.redis.register_script(lua_script)
            job_id = script(keys=[self._queue_key, self._processing_key, self._jobs_key],
                          args=[time.time(), worker_id])

            if not job_id:
                break

            job_data = self.redis.hget(self._jobs_key, job_id)
            if job_data:
                job = Job(**json.loads(job_data))
                job.status = JobStatus.PROCESSING
                job.worker_id = worker_id
                job.started_at = time.time()
                jobs.append(job)
        return jobs

    def update_job(self, job: Job) -> bool:
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            job.completed_at = time.time()
            self.redis.zrem(self._processing_key, job.id)
        self.redis.hset(self._jobs_key, job.id, json.dumps(asdict(job)))
        return True

    def get_job(self, job_id: str) -> Optional[Job]:
        job_data = self.redis.hget(self._jobs_key, job_id)
        return Job(**json.loads(job_data)) if job_data else None

    def get_jobs_by_user(self, user_id: str, limit: int = 50) -> List[Job]:
        # Scan all jobs (inefficient for large queues - use Redis sets per user in production)
        jobs = []
        cursor = 0
        while len(jobs) < limit:
            cursor, keys = self.redis.hscan(self._jobs_key, cursor, count=100)
            for key in keys:
                job_data = self.redis.hget(self._jobs_key, key)
                if job_data:
                    job = Job(**json.loads(job_data))
                    if job.user_id == user_id:
                        jobs.append(job)
                        if len(jobs) >= limit:
                            break
            if cursor == 0:
                break
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def cleanup_old(self, max_age_seconds: int) -> int:
        cutoff = time.time() - max_age_seconds
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = self.redis.hscan(self._jobs_key, cursor, count=100)
            for key in keys:
                job_data = self.redis.hget(self._jobs_key, key)
                if job_data:
                    job = Job(**json.loads(job_data))
                    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED) and job.completed_at > 0 and job.completed_at < cutoff:
                        self.redis.hdel(self._jobs_key, key)
                        self.redis.zrem(self._queue_key, key)
                        self.redis.zrem(self._processing_key, key)
                        deleted += 1
            if cursor == 0:
                break
        return deleted

    def get_stats(self) -> Dict:
        stats = {s.value: 0 for s in JobStatus}
        cursor = 0
        while True:
            cursor, keys = self.redis.hscan(self._jobs_key, cursor, count=500)
            for key in keys:
                job_data = self.redis.hget(self._jobs_key, key)
                if job_data:
                    job = Job(**json.loads(job_data))
                    stats[job.status.value] = stats.get(job.status.value, 0) + 1
            if cursor == 0:
                break
        stats["total"] = sum(stats.values())
        return stats


class HybridQueueBackend(QueueBackend):
    """Hybrid queue: SQLite for persistence + Redis for coordination."""

    def __init__(self, sqlite_path: str = "queue.db", redis_url: Optional[str] = None):
        self.sqlite = SQLiteQueueBackend(sqlite_path)
        self.redis = RedisQueueBackend(redis_url) if redis_url and REDIS_AVAILABLE else None

    def enqueue(self, job: Job) -> bool:
        self.sqlite.enqueue(job)
        if self.redis:
            self.redis.enqueue(job)
        return True

    def dequeue(self, worker_id: str, max_jobs: int = 1) -> List[Job]:
        if self.redis:
            return self.redis.dequeue(worker_id, max_jobs)
        return self.sqlite.dequeue(worker_id, max_jobs)

    def update_job(self, job: Job) -> bool:
        self.sqlite.update_job(job)
        if self.redis:
            self.redis.update_job(job)
        return True

    def get_job(self, job_id: str) -> Optional[Job]:
        # Try Redis first (faster), fallback to SQLite
        if self.redis:
            job = self.redis.get_job(job_id)
            if job:
                return job
        return self.sqlite.get_job(job_id)

    def get_jobs_by_user(self, user_id: str, limit: int = 50) -> List[Job]:
        return self.sqlite.get_jobs_by_user(user_id, limit)

    def cleanup_old(self, max_age_seconds: int) -> int:
        sqlite_deleted = self.sqlite.cleanup_old(max_age_seconds)
        redis_deleted = self.redis.cleanup_old(max_age_seconds) if self.redis else 0
        return sqlite_deleted + redis_deleted

    def get_stats(self) -> Dict:
        return self.sqlite.get_stats()


class JobQueue:
    """High-level job queue manager."""

    def __init__(self, backend: QueueBackend):
        self.backend = backend
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_cleanup = threading.Event()

    def start_cleanup(self, interval_seconds: int = 3600, max_age_seconds: int = 86400) -> None:
        """Start background cleanup thread."""
        self._stop_cleanup.clear()

        def cleanup_loop():
            while not self._stop_cleanup.wait(interval_seconds):
                try:
                    deleted = self.backend.cleanup_old(max_age_seconds)
                    if deleted:
                        logger.info("Cleaned up %d old jobs", deleted)
                except Exception as e:
                    logger.error("Queue cleanup failed: %s", sanitize_error_message(str(e)))

        self._cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def stop_cleanup(self) -> None:
        self._stop_cleanup.set()
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)

    def submit(self, user_id: str, input_path: str, params: Dict,
               priority: JobPriority = JobPriority.NORMAL) -> Job:
        """Submit a new job to the queue."""
        job = Job(
            id=str(uuid.uuid4())[:12],
            user_id=user_id,
            status=JobStatus.QUEUED,
            priority=priority,
            input_path=input_path,
            params=params,
        )
        self.backend.enqueue(job)
        logger.info("Job %s queued for user %s", job.id, user_id)
        return job

    def get_next_jobs(self, worker_id: str, max_jobs: int = 1) -> List[Job]:
        """Get next jobs for a worker."""
        return self.backend.dequeue(worker_id, max_jobs)

    def complete_job(self, job: Job, result: Dict = None, error: str = "") -> None:
        """Mark job as completed or failed."""
        job.status = JobStatus.FAILED if error else JobStatus.COMPLETED
        job.result = result or {}
        job.error = error
        job.completed_at = time.time()
        self.backend.update_job(job)

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.backend.get_job(job_id)

    def get_user_jobs(self, user_id: str, limit: int = 50) -> List[Job]:
        return self.backend.get_jobs_by_user(user_id, limit)

    def get_stats(self) -> Dict:
        return self.backend.get_stats()


# Global queue instance (initialized in app.py)
job_queue: Optional[JobQueue] = None


def init_queue(redis_url: Optional[str] = None, sqlite_path: str = "queue.db") -> JobQueue:
    """Initialize global job queue."""
    global job_queue
    if redis_url and REDIS_AVAILABLE:
        backend = HybridQueueBackend(sqlite_path, redis_url)
    else:
        backend = SQLiteQueueBackend(sqlite_path)
    job_queue = JobQueue(backend)
    job_queue.start_cleanup()
    return job_queue