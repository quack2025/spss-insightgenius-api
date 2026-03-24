"""Usage logging for billing and monitoring.

Logs every authenticated API request with:
- API key name and plan
- Endpoint and method
- File size (bytes)
- Processing time (ms)
- Response status code

Output goes to stdout (Railway captures it). Query via Railway logs or pipe to
any log aggregator (Datadog, Loki, etc.) for dashboards.

Log format: [USAGE] key=Acme plan=pro endpoint=/v1/frequency status=200 file_bytes=4096 time_ms=142
"""

import json
import logging
import time
from collections import defaultdict
from threading import Lock

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("quantipro.usage")

# In-memory usage counters (reset on deploy — for real-time monitoring only)
_usage_counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_counter_lock = Lock()


class UsageLoggerMiddleware:
    """Pure ASGI middleware that logs usage after each authenticated request."""

    SKIP_PATHS = {"/v1/health", "/docs", "/redoc", "/openapi.json", "/"}
    SKIP_PREFIXES = ("/mcp",)  # SSE/MCP streams break with send wrappers

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.SKIP_PATHS or any(path.startswith(p) for p in self.SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 0
        content_length = 0

        # Track request body size
        request_bytes = 0

        async def receive_wrapper():
            nonlocal request_bytes
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                request_bytes += len(body)
            return message

        async def send_wrapper(message):
            nonlocal status_code, content_length
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                for header_name, header_value in message.get("headers", []):
                    if header_name == b"content-length":
                        content_length = int(header_value)
            await send(message)

        await self.app(scope, receive_wrapper, send_wrapper)

        # Log usage after request completes
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        state = scope.get("state", {})
        key_config = state.get("key_config")

        if key_config:
            key_name = key_config.name
            plan = key_config.plan
            method = scope.get("method", "?")

            # Structured log line for billing
            logger.info(
                "[USAGE] key=%s plan=%s method=%s endpoint=%s status=%d "
                "request_bytes=%d response_bytes=%d time_ms=%d",
                key_name, plan, method, path, status_code,
                request_bytes, content_length, elapsed_ms,
            )

            # Update in-memory counters
            with _counter_lock:
                _usage_counters[key_name]["requests"] += 1
                _usage_counters[key_name]["bytes_in"] += request_bytes
                _usage_counters[key_name]["bytes_out"] += content_length
                _usage_counters[key_name][f"endpoint:{path}"] += 1
                if status_code >= 200 and status_code < 300:
                    _usage_counters[key_name]["success"] += 1
                else:
                    _usage_counters[key_name]["errors"] += 1


def get_usage_stats() -> dict[str, dict[str, int]]:
    """Return current in-memory usage stats (since last deploy)."""
    with _counter_lock:
        return {k: dict(v) for k, v in _usage_counters.items()}
