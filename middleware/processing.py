"""Concurrency limiter, timeout wrapper, and memory guard for CPU-bound processing.

All routers should use `run_in_executor()` instead of raw `asyncio.to_thread()`
to get automatic concurrency limits, request timeouts, and memory protection.

Architecture:
- Per-worker semaphore limits concurrent SPSS files in memory
- File size check prevents OOM from oversized uploads
- Memory guard rejects requests if RSS exceeds threshold
- Max-requests in gunicorn (1000) ensures periodic worker recycling
"""

import asyncio
import gc
import logging
import os
from typing import TypeVar, Callable

from config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Per-worker semaphore: limits how many SPSS files process simultaneously
_semaphore: asyncio.Semaphore | None = None

# Memory thresholds
MAX_RSS_MB = int(os.environ.get("MAX_RSS_MB", "400"))  # Reject new requests above this
MEMORY_WARNING_MB = int(MAX_RSS_MB * 0.75)

# Plan-based file size limits (MB)
PLAN_FILE_LIMITS = {
    "free": 5,
    "pro": 50,
    "business": 200,
    "enterprise": 500,
}


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        settings = get_settings()
        _semaphore = asyncio.Semaphore(settings.max_concurrent_processing)
        logger.info("Processing semaphore initialized: max %d concurrent jobs", settings.max_concurrent_processing)
    return _semaphore


def get_memory_mb() -> float:
    """Get current process RSS in MB."""
    try:
        # Linux/Railway
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024  # KB to MB
    except (FileNotFoundError, ValueError):
        pass
    try:
        # Windows/Mac fallback
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0  # Can't measure — allow through


def check_memory_available() -> bool:
    """Check if we have enough memory to process another file."""
    rss = get_memory_mb()
    if rss > MAX_RSS_MB:
        logger.warning("Memory guard: RSS=%.0fMB exceeds MAX_RSS_MB=%d. Rejecting request.", rss, MAX_RSS_MB)
        return False
    if rss > MEMORY_WARNING_MB:
        logger.info("Memory warning: RSS=%.0fMB approaching limit of %dMB", rss, MAX_RSS_MB)
    return True


def validate_file_size(file_bytes: bytes, plan: str = "free") -> None:
    """Validate file size against plan limits.

    Raises:
        ValueError: If file exceeds plan limit.
    """
    size_mb = len(file_bytes) / (1024 * 1024)
    limit_mb = PLAN_FILE_LIMITS.get(plan, PLAN_FILE_LIMITS["free"])
    if size_mb > limit_mb:
        raise ValueError(
            f"File size ({size_mb:.1f}MB) exceeds your plan limit ({limit_mb}MB). "
            f"Upgrade to a higher plan for larger files."
        )


async def run_in_executor(fn: Callable[..., T], *args, timeout: float | None = None) -> T:
    """Run a CPU-bound function with concurrency limiting, timeout, and memory guard.

    Args:
        fn: Blocking function to run in thread pool.
        *args: Arguments to pass to fn.
        timeout: Max seconds to wait. None = use config default.

    Raises:
        asyncio.TimeoutError: If processing exceeds timeout.
        RuntimeError: If too many requests queued or memory too high.
    """
    if timeout is None:
        timeout = float(get_settings().processing_timeout_seconds)

    # Memory guard
    if not check_memory_available():
        gc.collect()  # Try to free memory first
        if not check_memory_available():
            raise RuntimeError(
                "Server memory is critically high. Please retry in a few seconds. "
                "If this persists, try a smaller file."
            )

    sem = _get_semaphore()

    # Try to acquire semaphore with a short wait — don't queue forever
    try:
        acquired = await asyncio.wait_for(sem.acquire(), timeout=10.0)
    except asyncio.TimeoutError:
        raise RuntimeError(
            "Server is processing too many files simultaneously. Please retry in a few seconds."
        )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(fn, *args),
            timeout=timeout,
        )
        return result
    finally:
        sem.release()
        # Force garbage collection after large file processing
        gc.collect()
