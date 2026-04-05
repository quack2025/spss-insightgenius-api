"""Idempotency middleware for POST endpoints (pure ASGI).

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

from starlette.types import ASGIApp, Receive, Scope, Send

from config import get_settings

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL = 300  # 5 minutes

# In-memory cache (fallback when Redis not available)
_cache: dict[str, dict[str, Any]] = {}
_cache_max = 1000


class IdempotencyMiddleware:
    """Pure ASGI middleware — caches POST responses by Idempotency-Key header."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Only POST requests with Idempotency-Key
        method = scope.get("method", "")
        if method != "POST":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        idem_key = (headers.get(b"idempotency-key") or b"").decode()
        if not idem_key:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        cache_key = f"idem:{path}:{hashlib.sha256(idem_key.encode()).hexdigest()[:16]}"

        # Check cache
        cached = await _get(cache_key)
        if cached:
            logger.info("[IDEMPOTENCY] Cache hit for key=%s path=%s", idem_key[:12], path)
            # Replay cached response
            resp_headers = [(k.encode() if isinstance(k, str) else k,
                             v.encode() if isinstance(v, str) else v)
                            for k, v in cached.get("headers", {}).items()]
            resp_headers.append((b"x-idempotent-replay", b"true"))
            await send({
                "type": "http.response.start",
                "status": cached["status"],
                "headers": resp_headers,
            })
            body = cached.get("body", "")
            if isinstance(body, str):
                body = body.encode()
            await send({
                "type": "http.response.body",
                "body": body,
            })
            return

        # Capture response for caching
        response_started = False
        status_code = 0
        response_headers: list = []
        body_parts: list[bytes] = []

        async def send_wrapper(message):
            nonlocal response_started, status_code, response_headers
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message.get("status", 0)
                response_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    body_parts.append(chunk)
            await send(message)

        await self.app(scope, receive, send_wrapper)

        # Cache successful responses
        if 200 <= status_code < 300 and body_parts:
            header_dict = {}
            media_type = "application/json"
            for k, v in response_headers:
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                header_dict[key] = val
                if key.lower() == "content-type":
                    media_type = val

            await _set(cache_key, {
                "body": b"".join(body_parts),
                "status": status_code,
                "media_type": media_type,
                "headers": header_dict,
            })


async def _get(key: str) -> dict | None:
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

    entry = _cache.get(key)
    if entry and time.time() - entry.get("_ts", 0) < IDEMPOTENCY_TTL:
        return entry
    return None


async def _set(key: str, value: dict) -> None:
    """Store in Redis or memory cache."""
    settings = get_settings()
    if settings.redis_url:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.redis_url, decode_responses=False)
            # Convert bytes body to string for JSON serialization
            store_val = {**value}
            if isinstance(store_val.get("body"), bytes):
                store_val["body"] = store_val["body"].decode("utf-8", errors="replace")
            await r.setex(key, IDEMPOTENCY_TTL, json.dumps(store_val, default=str))
            await r.aclose()
            return
        except Exception:
            pass

    # Memory fallback
    if len(_cache) >= _cache_max:
        oldest = sorted(_cache.items(), key=lambda x: x[1].get("_ts", 0))[:100]
        for k, _ in oldest:
            _cache.pop(k, None)
    value["_ts"] = time.time()
    _cache[key] = value
