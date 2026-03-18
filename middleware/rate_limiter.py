"""In-memory per-key rate limiter with sliding window. No Redis required.

Used as a FastAPI dependency (not middleware) so it runs after auth.
"""

import time
import logging
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request

from config import get_settings

logger = logging.getLogger(__name__)

# Sliding window state: key_hash -> list of timestamps
_windows: dict[str, list[float]] = defaultdict(list)
_lock = Lock()
_WINDOW_SECONDS = 60


def _cleanup_window(timestamps: list[float], now: float) -> list[float]:
    cutoff = now - _WINDOW_SECONDS
    return [t for t in timestamps if t > cutoff]


async def check_rate_limit(request: Request) -> None:
    """FastAPI dependency: check rate limit for the authenticated key.

    Must be used AFTER require_auth/require_scope in the dependency chain.
    Sets rate limit headers on the response via request.state.
    """
    key_config = getattr(request.state, "key_config", None)
    if key_config is None:
        return  # No auth → no rate limiting

    settings = get_settings()
    limit = settings.rate_limit_for_plan(key_config.plan)
    now = time.time()

    with _lock:
        window = _cleanup_window(_windows[key_config.key_hash], now)
        _windows[key_config.key_hash] = window

        if len(window) >= limit:
            reset_at = window[0] + _WINDOW_SECONDS
            retry_after = max(1, int(reset_at - now))
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Rate limit exceeded. {limit} requests per minute allowed for '{key_config.plan}' plan.",
                },
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(reset_at)),
                    "Retry-After": str(retry_after),
                },
            )

        window.append(now)
        remaining = limit - len(window)

    # Store for response headers (routers can use this)
    request.state.rate_limit_headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Reset": str(int(now + _WINDOW_SECONDS)),
    }
