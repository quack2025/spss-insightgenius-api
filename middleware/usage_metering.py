"""Persistent usage metering — tracks every API call to Supabase for billing.

Runs asynchronously after the response is sent (fire-and-forget).
Does NOT block or slow down the response.

Tables used:
- usage_daily: per-user per-day aggregates
- Supabase RPC: increment_usage(p_user_id, p_endpoint, p_bytes, p_is_file_upload)
"""

import asyncio
import logging
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from config import get_settings

logger = logging.getLogger(__name__)

SKIP_PATHS = {"/v1/health", "/docs", "/redoc", "/openapi.json", "/", "/static/config.js"}
SKIP_PREFIXES = ("/mcp", "/static")


class UsageMeteringMiddleware:
    """Fire-and-forget usage tracking to Supabase after each authenticated request."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in SKIP_PATHS or any(path.startswith(p) for p in SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        request_bytes = 0

        async def receive_wrapper():
            nonlocal request_bytes
            message = await receive()
            if message.get("type") == "http.request":
                request_bytes += len(message.get("body", b""))
            return message

        await self.app(scope, receive_wrapper, send)

        # Fire-and-forget metering
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        state = scope.get("state", {})
        key_config = state.get("key_config")

        if key_config and key_config.name != "demo":
            is_upload = "upload" in path or "files" in path
            asyncio.create_task(_track_usage(
                user_id=key_config.name,
                endpoint=path,
                bytes_processed=request_bytes,
                is_file_upload=is_upload,
            ))


async def _track_usage(user_id: str, endpoint: str, bytes_processed: int, is_file_upload: bool):
    """Track usage to Supabase (non-blocking, fire-and-forget)."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{settings.supabase_url}/rest/v1/rpc/increment_usage",
                headers={
                    "apikey": settings.supabase_service_role_key,
                    "Authorization": f"Bearer {settings.supabase_service_role_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "p_user_id": user_id,
                    "p_endpoint": endpoint,
                    "p_bytes": bytes_processed,
                    "p_is_file_upload": is_file_upload,
                },
            )
            if resp.status_code not in (200, 204):
                logger.warning("[METERING] Failed to track usage: %s", resp.text[:200])
    except Exception as e:
        # Never block the response — metering failures are non-critical
        logger.debug("[METERING] Error (non-blocking): %s", e)
