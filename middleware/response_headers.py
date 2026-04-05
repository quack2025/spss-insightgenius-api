"""Pure ASGI middleware to inject standard response headers.

Uses raw ASGI protocol instead of BaseHTTPMiddleware to avoid
Starlette's known AssertionError on empty/streaming responses.
"""

import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

API_VERSION = "2026-03-28"

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
]


class ResponseHeadersMiddleware:
    """Pure ASGI middleware — injects headers into every HTTP response."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())[:8]
        # Store request_id in scope state for downstream use
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"api-version", API_VERSION.encode()))
                headers.extend(SECURITY_HEADERS)

                # Add rate limit headers if set
                rl_headers = scope.get("state", {}).get("rate_limit_headers")
                if rl_headers:
                    for k, v in rl_headers.items():
                        headers.append((k.lower().encode(), str(v).encode()))

                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
