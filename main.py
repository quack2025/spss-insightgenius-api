"""QuantiPro API — SPSS processing microservice powered by QuantipyMRX + Haiku."""

import asyncio
import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from auth import init_key_registry
from config import get_settings
from middleware.idempotency import IdempotencyMiddleware
from middleware.response_headers import ResponseHeadersMiddleware
from middleware.usage_logger import UsageLoggerMiddleware
from middleware.usage_metering import UsageMeteringMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown events."""
    settings = get_settings()
    logger.info("Starting %s v%s (%s)", settings.app_name, settings.app_version, settings.app_env)

    # Load API keys into memory
    init_key_registry()

    # Validate Anthropic key presence (warn, don't crash — Haiku features will be disabled)
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — ticket parsing and smart labeling will be disabled")

    # Start MCP Redis relay for cross-replica SSE session routing
    from mcp_server import start_redis_relay, stop_redis_relay
    await start_redis_relay()

    yield

    await stop_redis_relay()
    logger.info("Shutting down %s", settings.app_name)


def create_application() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "**SPSS InsightGenius API** — REST API for processing SPSS (.sav) files.\n\n"
            "Powered by QuantipyMRX for market research analysis: crosstabs with significance testing, "
            "auto-detection of question types, NPS, Top/Bottom Box, nets, and AI-powered "
            "Reporting Ticket parsing via Claude Haiku.\n\n"
            "## Authentication\n"
            "All endpoints require `Authorization: Bearer sk_live_...` or `sk_test_...`\n\n"
            "## Rate Limits\n"
            "| Plan | Requests/min | Max file size |\n"
            "|------|-------------|---------------|\n"
            "| Free (sk_test_) | 10 | 5 MB |\n"
            "| Pro | 60 | 50 MB |\n"
            "| Business | 200 | 200 MB |\n"
        ),
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "System", "description": "Health check and system info"},
            {"name": "Metadata", "description": "Extract variable metadata from SPSS files"},
            {"name": "Analysis", "description": "Frequency, crosstab, NPS, and other analyses"},
            {"name": "Processing", "description": "Full pipeline: upload + analyze + return results"},
            {"name": "Conversion", "description": "Convert SPSS files to other formats"},
            {"name": "AI Features", "description": "Haiku-powered ticket parsing and smart labeling"},
        ],
    )

    # Middleware stack (outermost first):
    # 1. Usage logger — logs every authenticated request for billing
    # 2. CORS — allow cross-origin requests
    app.add_middleware(UsageMeteringMiddleware)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(ResponseHeadersMiddleware)
    app.add_middleware(UsageLoggerMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.parsed_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "API-Version", "X-RateLimit-Limit",
                        "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )

    # Standardized error handlers using shared.response.error_response
    from shared.response import error_response

    @app.exception_handler(asyncio.TimeoutError)
    async def timeout_handler(request: Request, exc: asyncio.TimeoutError):
        logger.warning("Processing timeout [%s]", getattr(request.state, "request_id", ""))
        return JSONResponse(status_code=504, content=error_response(
            "PROCESSING_TIMEOUT",
            f"Processing exceeded {settings.processing_timeout_seconds}s limit. Try a smaller file or fewer stubs.",
        ))

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError):
        if "too many files" in str(exc).lower():
            logger.warning("Concurrency limit [%s]: %s", getattr(request.state, "request_id", ""), exc)
            return JSONResponse(status_code=503, content=error_response(
                "SERVER_BUSY", str(exc),
            ), headers={"Retry-After": "5"})
        return await global_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception [%s]: %s", getattr(request.state, "request_id", ""), exc, exc_info=True)
        return JSONResponse(status_code=500, content=error_response(
            "PROCESSING_FAILED",
            "Internal server error" if settings.is_production else str(exc),
        ))

    # OAuth 2.0 discovery endpoints (RFC 9728)
    @app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
    async def oauth_protected_resource():
        """RFC 9728 Protected Resource Metadata — tells Claude.ai where to find the auth server."""
        clerk_url = settings.clerk_frontend_api
        return {
            "resource": settings.base_url,
            "authorization_servers": [clerk_url] if clerk_url else [],
            "scopes_supported": ["openid", "profile", "email"],
            "bearer_methods_supported": ["header"],
        }

    # Register routers
    from routers.health import router as health_router
    from routers.metadata import router as metadata_router
    from routers.frequency import router as frequency_router
    from routers.crosstab import router as crosstab_router
    from routers.convert import router as convert_router
    from routers.parse_ticket import router as parse_ticket_router
    from routers.process import router as process_router
    from routers.tabulate import router as tabulate_router
    from routers.correlation import router as correlation_router
    from routers.anova import router as anova_router
    from routers.gap_analysis import router as gap_router
    from routers.satisfaction import router as satisfaction_router
    from routers.auto_analyze import router as auto_analyze_router
    from routers.downloads import router as downloads_router
    from routers.file_upload import router as file_upload_router
    from routers.weight import router as weight_router
    from routers.chat import router as chat_router
    from routers.chat_stream import router as chat_stream_router
    from routers.keys import router as keys_router
    from routers.smart_spec import router as smart_spec_router
    from routers.library import router as library_router

    app.include_router(health_router)
    app.include_router(metadata_router)
    app.include_router(frequency_router)
    app.include_router(crosstab_router)
    app.include_router(convert_router)
    app.include_router(parse_ticket_router)
    app.include_router(process_router)
    app.include_router(tabulate_router)
    app.include_router(correlation_router)
    app.include_router(anova_router)
    app.include_router(gap_router)
    app.include_router(satisfaction_router)
    app.include_router(auto_analyze_router)
    app.include_router(downloads_router)
    app.include_router(file_upload_router)
    app.include_router(weight_router)
    app.include_router(chat_router)
    app.include_router(chat_stream_router)
    app.include_router(keys_router)
    app.include_router(smart_spec_router)
    app.include_router(library_router)

    # MCP server — SSE transport
    # NOTE: Streamable HTTP (http_app) CANNOT be mounted as FastAPI sub-app —
    # it requires run() to initialize an anyio task group, which doesn't happen
    # when mounted. See Railway logs: "Task group is not initialized."
    # Streamable HTTP requires running FastMCP as standalone server, not embedded.
    # When FastMCP fixes this, re-enable at /mcp with http_app(path="/").
    from mcp_server import get_mcp_asgi_app
    app.mount("/mcp", get_mcp_asgi_app())
    logger.info("MCP SSE mounted at /mcp/sse")

    # NOTE: SSE deprecation header REMOVED — middleware breaks SSE streaming responses.
    # Deprecation will be communicated via spss_get_server_info tool response instead.

    # Demo key injection — served as JS so the key isn't in the git repo
    @app.get("/static/config.js", include_in_schema=False)
    async def demo_config():
        demo_key = settings.demo_api_key or "demo"
        from starlette.responses import Response
        return Response(
            content=f"window.__INSIGHTGENIUS_DEMO_KEY__ = '{demo_key}';",
            media_type="application/javascript",
        )

    # Serve frontend + static pages
    public_dir = Path(__file__).parent / "public"
    if public_dir.exists():
        # Landing page (new Stitch design)
        @app.get("/", include_in_schema=False)
        async def root():
            return FileResponse(public_dir / "index.html")

        # Auth pages
        @app.get("/login", include_in_schema=False)
        async def login_page():
            return FileResponse(public_dir / "login.html")

        @app.get("/signup", include_in_schema=False)
        async def signup_page():
            return FileResponse(public_dir / "signup.html")

        # Dashboard pages
        @app.get("/app", include_in_schema=False)
        async def app_page():
            return FileResponse(public_dir / "app.html")

        @app.get("/export", include_in_schema=False)
        async def export_page():
            return FileResponse(public_dir / "app.html")

        @app.get("/express", include_in_schema=False)
        async def express_page():
            return FileResponse(public_dir / "express.html")

        @app.get("/wizard", include_in_schema=False)
        async def wizard_page():
            return FileResponse(public_dir / "wizard.html")

        @app.get("/export-mcp", include_in_schema=False)
        async def export_mcp_page():
            return FileResponse(public_dir / "chat.html")

        @app.get("/upload", include_in_schema=False)
        async def upload_page():
            return FileResponse(public_dir / "upload.html")

        @app.get("/app/dashboard", include_in_schema=False)
        async def dashboard_page():
            return FileResponse(public_dir / "dashboard.html")

        @app.get("/app/keys", include_in_schema=False)
        async def api_keys_page():
            return FileResponse(public_dir / "api-keys.html")

        @app.get("/app/billing", include_in_schema=False)
        async def billing_page():
            return FileResponse(public_dir / "billing.html")

        # Info pages
        @app.get("/privacy", include_in_schema=False)
        async def privacy():
            return FileResponse(public_dir / "privacy.html")

        @app.get("/docs/mcp", include_in_schema=False)
        async def mcp_docs():
            return FileResponse(public_dir / "mcp-docs.html")

        app.mount("/static", StaticFiles(directory=str(public_dir)), name="static")
    else:
        @app.get("/", include_in_schema=False)
        async def root():
            return {"name": settings.app_name, "version": settings.app_version, "docs": "/docs"}

    return app


app = create_application()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=not settings.is_production,
    )
