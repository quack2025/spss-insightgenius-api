"""Data Manager — caches DataFrames for project-based analysis.

Provides get_project_data() which:
1. Loads SPSS bytes from Redis cache or Supabase Storage
2. Parses with pyreadstat (via quantipy_engine)
3. Caches the parsed DataFrame with TTL
4. Returns SPSSData ready for quantipy_engine methods

Uses an LRU+TTL cache to bound memory usage.
"""

import asyncio
import logging
import time
from typing import Any

from services.quantipy_engine import QuantiProEngine, SPSSData

logger = logging.getLogger(__name__)

# In-memory TTL+LRU cache
_cache: dict[str, tuple[SPSSData, float]] = {}
_MAX_CACHE_SIZE = 20
_CACHE_TTL_SECONDS = 3600  # 1 hour


def _evict_expired() -> None:
    """Remove expired entries."""
    now = time.time()
    expired = [k for k, (_, ts) in _cache.items() if now - ts > _CACHE_TTL_SECONDS]
    for k in expired:
        del _cache[k]


def _evict_lru() -> None:
    """Remove oldest entries if over max size."""
    if len(_cache) >= _MAX_CACHE_SIZE:
        oldest_key = min(_cache, key=lambda k: _cache[k][1])
        del _cache[oldest_key]


async def get_project_data(project_id: str, file_bytes: bytes | None = None) -> SPSSData:
    """Get parsed SPSS data for a project.

    Args:
        project_id: UUID string of the project
        file_bytes: Raw SPSS file bytes (if already available)

    Returns:
        SPSSData with df, meta, mrx_dataset
    """
    cache_key = f"project:{project_id}"

    # Check cache
    _evict_expired()
    if cache_key in _cache:
        data, _ = _cache[cache_key]
        _cache[cache_key] = (data, time.time())  # refresh TTL
        return data

    if file_bytes is None:
        # Try to load from Redis session
        file_bytes = await _load_from_redis(project_id)

    if file_bytes is None:
        raise ValueError(f"No data available for project {project_id}. Upload a file first.")

    # Parse SPSS in thread (blocking I/O)
    spss_data = await asyncio.to_thread(QuantiProEngine.load_spss, file_bytes)

    # Cache it
    _evict_lru()
    _cache[cache_key] = (spss_data, time.time())

    return spss_data


def invalidate_project_cache(project_id: str) -> None:
    """Remove cached data for a project (e.g., after data prep changes)."""
    cache_key = f"project:{project_id}"
    _cache.pop(cache_key, None)


async def _load_from_redis(project_id: str) -> bytes | None:
    """Try to load file bytes from Redis cache."""
    from config import get_settings
    settings = get_settings()

    if not settings.redis_url:
        return None

    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=False)
        try:
            # Try project-specific key first
            data = await r.get(f"spss_session:{project_id}:data")
            if data:
                return data
            # Try file_id key (from file upload)
            data = await r.get(f"spss:file:{project_id}")
            return data
        finally:
            await r.aclose()
    except Exception as e:
        logger.debug("Redis load failed for %s: %s", project_id, e)
        return None
