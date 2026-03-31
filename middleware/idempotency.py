"""Idempotency middleware for POST endpoints.

Clients can send an `Idempotency-Key` header with any POST request.
If the same key is seen again within the TTL, the cached response is returned
instead of re-processing. This prevents duplicate work from network retries.

Storage: Redis (if available) or in-memory dict (single-replica only).
TTL: 5 minutes (configurable).
"""

import hashlib
import json
import logging
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from config import get_settings

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL = 300  # 5 minutes

# In-memory cache (fallback when Redis not available)
_cache: dict[str, dict[str, Any]] = {}
_cache_max = 1000


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Cache POST responses by Idempotency-Key header."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method != "POST":
            return await call_next(request)

        idem_key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
        if not idem_key:
            return await call_next(request)

        # Normalize key with path for uniqueness
        cache_key = f"idem:{request.url.path}:{hashlib.sha256(idem_key.encode()).hexdigest()[:16]}"

        # Check cache
        cached = await self._get(cache_key)
        if cached:
            logger.info("[IDEMPOTENCY] Cache hit for key=%s path=%s", idem_key[:12], request.url.path)
            return Response(
                content=cached["body"],
                status_code=cached["status"],
                headers={**cached.get("headers", {}), "X-Idempotent-Replay": "true"},
                media_type=cached.get("media_type", "application/json"),
            )

        # Process request
        response = await call_next(request)

        # Cache response (only for success)
        if 200 <= response.status_code < 300:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk if isinstance(chunk, bytes) else chunk.encode()

            await self._set(cache_key, {
                "body": body,
                "status": response.status_code,
                "media_type": response.media_type,
                "headers": dict(response.headers),
            })

            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        return response

    async def _get(self, key: str) -> dict | None:
        """Get from Redis or memory cache."""
        settings = get_settings()
        if settings.redis_url:
            try:
                import redis.asyncio as aioredis
                r = aioredis.from_url(settings.redis_url, decode_responses=False)
                data = await r.get(key)
                await r.aclose()
                if data:
                    return json.loads(data)
            except Exception:
                pass

        # Memory fallback
        entry = _cache.get(key)
        if entry and time.time() - entry.get("_ts", 0) < IDEMPOTENCY_TTL:
            return entry
        return None

    async def _set(self, key: str, value: dict) -> None:
        """Store in Redis or memory cache."""
        settings = get_settings()
        if settings.redis_url:
            try:
                import redis.asyncio as aioredis
                r = aioredis.from_url(settings.redis_url, decode_responses=False)
                await r.setex(key, IDEMPOTENCY_TTL, json.dumps(value, default=str))
                await r.aclose()
                return
            except Exception:
                pass

        # Memory fallback
        if len(_cache) >= _cache_max:
            # Evict oldest entries
            oldest = sorted(_cache.items(), key=lambda x: x[1].get("_ts", 0))[:100]
            for k, _ in oldest:
                _cache.pop(k, None)
        value["_ts"] = time.time()
        _cache[key] = value
