"""Middleware to inject standard response headers: rate limits, API version, request ID."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from config import get_settings

API_VERSION = "2026-03-28"


class ResponseHeadersMiddleware(BaseHTTPMiddleware):
    """Injects standard headers into every API response:
    - X-Request-Id: unique request identifier
    - API-Version: current API version date
    - X-RateLimit-*: rate limit info (if authenticated)
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Generate request ID
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception:
            # BaseHTTPMiddleware can crash on certain empty responses;
            # fall through without headers rather than killing the request.
            from starlette.responses import Response as StarletteResponse
            response = StarletteResponse(status_code=500)

        # Always add these
        response.headers["X-Request-Id"] = request_id
        response.headers["API-Version"] = API_VERSION
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Add rate limit headers if they were set by check_rate_limit
        rl_headers = getattr(request.state, "rate_limit_headers", None)
        if rl_headers:
            for key, value in rl_headers.items():
                response.headers[key] = value

        return response
