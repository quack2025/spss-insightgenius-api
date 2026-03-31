"""Health check and usage monitoring endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from auth import require_auth, KeyConfig
from config import get_settings

router = APIRouter(tags=["System"])

# Check QuantipyMRX availability at import time
try:
    from quantipymrx import DataSet as _MRXCheck
    _QUANTIPYMRX_AVAILABLE = True
except ImportError:
    _QUANTIPYMRX_AVAILABLE = False


@router.get("/v1/health")
async def health():
    settings = get_settings()
    from middleware.processing import get_memory_mb, MAX_RSS_MB
    rss = get_memory_mb()
    return {
        "status": "ok",
        "version": settings.app_version,
        "engine": "quantipymrx",
        "quantipymrx_available": _QUANTIPYMRX_AVAILABLE,
        "environment": settings.app_env,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "memory_mb": round(rss, 1),
        "memory_limit_mb": MAX_RSS_MB,
        "memory_pct": round(rss / MAX_RSS_MB * 100, 1) if MAX_RSS_MB > 0 else 0,
    }


@router.get("/v1/usage", summary="Usage stats (since last deploy)", tags=["System"])
async def usage(key: KeyConfig = Depends(require_auth)):
    """Returns per-key usage counters since last deploy.
    Requires authentication. Each key only sees its own stats.
    """
    from middleware.usage_logger import get_usage_stats
    all_stats = get_usage_stats()
    my_stats = all_stats.get(key.name, {})
    return {
        "success": True,
        "data": {
            "key_name": key.name,
            "plan": key.plan,
            "stats": my_stats,
            "note": "Counters reset on each deploy. For persistent billing, use Railway log aggregation.",
        },
    }
