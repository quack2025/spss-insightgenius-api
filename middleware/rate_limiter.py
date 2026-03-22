"""Per-key rate limiter with sliding window.

Uses Redis when available (distributed, multi-replica safe).
Falls back to in-memory dict for local dev / single-replica.
"""

import time
import logging
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request

from config import get_settings

logger = logging.getLogger(__name__)

# ── Redis backend ──────────────────────────────────────────────────────────

_redis_client = None
_redis_init_done = False


def _get_redis():
    """Lazy-init Redis connection. Returns None if unavailable."""
    global _redis_client, _redis_init_done
    if _redis_init_done:
        return _redis_client

    _redis_init_done = True
    settings = get_settings()
    redis_url = settings.redis_url
    if not redis_url:
        logger.info("REDIS_URL not set — using in-memory rate limiter (single-replica only)")
        return None

    try:
        import redis
        _redis_client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=1,
            retry_on_timeout=True,
        )
        _redis_client.ping()
        logger.info("Redis rate limiter connected: %s", redis_url.split("@")[-1] if "@" in redis_url else "localhost")
        return _redis_client
    except Exception as e:
        logger.warning("Redis unavailable (%s) — falling back to in-memory rate limiter", e)
        _redis_client = None
        return None


_WINDOW_SECONDS = 60


def _check_rate_redis(r, key_hash: str, limit: int, now: float) -> tuple[int, float]:
    """Redis sorted-set sliding window. Returns (remaining, reset_at).

    Raises HTTPException(429) if limit exceeded.
    """
    rkey = f"rl:{key_hash}"
    pipe = r.pipeline(transaction=True)
    cutoff = now - _WINDOW_SECONDS

    pipe.zremrangebyscore(rkey, "-inf", cutoff)  # remove expired
    pipe.zcard(rkey)                              # current count
    pipe.zadd(rkey, {f"{now}": now})              # add this request
    pipe.expire(rkey, _WINDOW_SECONDS + 1)        # auto-cleanup
    results = pipe.execute()

    current_count = results[1]  # count BEFORE adding this request

    if current_count >= limit:
        # Over limit — remove the entry we just added
        r.zrem(rkey, f"{now}")
        # Find oldest entry to compute reset time
        oldest = r.zrange(rkey, 0, 0, withscores=True)
        reset_at = oldest[0][1] + _WINDOW_SECONDS if oldest else now + _WINDOW_SECONDS
        retry_after = max(1, int(reset_at - now))
        raise HTTPException(
            status_code=429,
            detail={
                "code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit exceeded. {limit} requests per minute allowed.",
            },
            headers={
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(reset_at)),
                "Retry-After": str(retry_after),
            },
        )

    remaining = limit - current_count - 1
    reset_at = now + _WINDOW_SECONDS
    return remaining, reset_at


# ── In-memory fallback ─────────────────────────────────────────────────────

_windows: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def _cleanup_window(timestamps: list[float], now: float) -> list[float]:
    cutoff = now - _WINDOW_SECONDS
    return [t for t in timestamps if t > cutoff]


def _check_rate_memory(key_hash: str, limit: int, now: float) -> tuple[int, float]:
    """In-memory sliding window. Returns (remaining, reset_at).

    Raises HTTPException(429) if limit exceeded.
    """
    with _lock:
        window = _cleanup_window(_windows[key_hash], now)
        _windows[key_hash] = window

        if len(window) >= limit:
            reset_at = window[0] + _WINDOW_SECONDS
            retry_after = max(1, int(reset_at - now))
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Rate limit exceeded. {limit} requests per minute allowed.",
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

    reset_at = now + _WINDOW_SECONDS
    return remaining, reset_at


# ── FastAPI dependency ─────────────────────────────────────────────────────

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

    r = _get_redis()
    if r is not None:
        try:
            remaining, reset_at = _check_rate_redis(r, key_config.key_hash, limit, now)
        except HTTPException:
            raise
        except Exception as e:
            # Redis error — fall back to memory for this request
            logger.warning("Redis rate-limit error (%s), falling back to memory", e)
            remaining, reset_at = _check_rate_memory(key_config.key_hash, limit, now)
    else:
        remaining, reset_at = _check_rate_memory(key_config.key_hash, limit, now)

    # Store for response headers
    request.state.rate_limit_headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Reset": str(int(reset_at)),
    }
