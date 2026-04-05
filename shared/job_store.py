"""In-memory job store with optional Redis persistence.

Jobs track async processing requests (tabulation, auto-analyze).
Each job has: id, status, endpoint, user_id, webhook_url, result, timestamps.
"""

import time
import uuid
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# In-memory store (per-worker). Not shared across Uvicorn workers.
# Redis upgrade planned for cross-worker visibility.
_jobs: dict[str, dict] = {}

# Jobs older than this are evicted on next create/get
_JOB_TTL_SECONDS = 3600  # 1 hour


def _evict_expired() -> None:
    """Remove jobs older than TTL to prevent unbounded memory growth."""
    cutoff = time.time() - _JOB_TTL_SECONDS
    expired = [jid for jid, j in _jobs.items() if j["updated_at"] < cutoff]
    for jid in expired:
        del _jobs[jid]


class JobStore:
    """Manages async job lifecycle. In-memory with TTL eviction."""

    def create(
        self,
        user_id: str,
        endpoint: str,
        webhook_url: Optional[str] = None,
    ) -> str:
        _evict_expired()
        job_id = str(uuid.uuid4())
        _jobs[job_id] = {
            "id": job_id,
            "status": JobStatus.PENDING,
            "endpoint": endpoint,
            "user_id": user_id,
            "webhook_url": webhook_url,
            "result": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        return job_id

    def get(self, job_id: str) -> Optional[dict]:
        _evict_expired()
        return _jobs.get(job_id)

    def update(self, job_id: str, status: JobStatus) -> None:
        if job_id in _jobs:
            _jobs[job_id]["status"] = status
            _jobs[job_id]["updated_at"] = time.time()

    def complete(self, job_id: str, download_url: str) -> None:
        if job_id in _jobs:
            _jobs[job_id]["status"] = JobStatus.DONE
            _jobs[job_id]["result"] = {"download_url": download_url}
            _jobs[job_id]["updated_at"] = time.time()

    def fail(self, job_id: str, error_code: str, error_message: str) -> None:
        if job_id in _jobs:
            _jobs[job_id]["status"] = JobStatus.FAILED
            _jobs[job_id]["result"] = {
                "error": {"code": error_code, "message": error_message},
            }
            _jobs[job_id]["updated_at"] = time.time()
