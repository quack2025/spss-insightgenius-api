"""Concurrency limiter and timeout wrapper for CPU-bound processing.

All routers should use `run_in_executor()` instead of raw `asyncio.to_thread()`
to get automatic concurrency limits and request timeouts.
"""

import asyncio
import logging
from functools import partial
from typing import TypeVar, Callable

from config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Per-worker semaphore: limits how many SPSS files process simultaneously
# within a single uvicorn worker. Prevents OOM from too many concurrent
# large DataFrames in memory.
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        settings = get_settings()
        _semaphore = asyncio.Semaphore(settings.max_concurrent_processing)
        logger.info("Processing semaphore initialized: max %d concurrent jobs", settings.max_concurrent_processing)
    return _semaphore


async def run_in_executor(fn: Callable[..., T], *args, timeout: float | None = None) -> T:
    """Run a CPU-bound function with concurrency limiting and timeout.

    Args:
        fn: Blocking function to run in thread pool.
        *args: Arguments to pass to fn.
        timeout: Max seconds to wait. None = use config default.

    Raises:
        asyncio.TimeoutError: If processing exceeds timeout.
        RuntimeError: If too many requests are queued (semaphore contention).
    """
    if timeout is None:
        timeout = float(get_settings().processing_timeout_seconds)

    sem = _get_semaphore()

    # Try to acquire semaphore with a short wait — don't queue forever
    try:
        acquired = await asyncio.wait_for(sem.acquire(), timeout=10.0)
    except asyncio.TimeoutError:
        raise RuntimeError(
            "Server is processing too many files simultaneously. Please retry in a few seconds."
        )

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args),
            timeout=timeout,
        )
    finally:
        sem.release()
