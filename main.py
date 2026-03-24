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
from middleware.usage_logger import UsageLoggerMiddleware

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
    from routers.mcp_server import start_redis_relay, stop_redis_relay
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
    app.add_middleware(UsageLoggerMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.parsed_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Timeout handler — from run_in_executor
    @app.exception_handler(asyncio.TimeoutError)
    async def timeout_handler(request: Request, exc: asyncio.TimeoutError):
        request_id = getattr(request.state, "request_id", "")
        logger.warning("Processing timeout [%s]", request_id)
        return JSONResponse(
            status_code=504,
            content={
                "success": False,
                "error": {
                    "code": "PROCESSING_TIMEOUT",
                    "message": f"Processing exceeded {settings.processing_timeout_seconds}s limit. Try a smaller file or fewer stubs.",
                },
                "request_id": request_id,
            },
        )

    # Concurrency overload handler — from run_in_executor
    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError):
        request_id = getattr(request.state, "request_id", "")
        if "too many files" in str(exc).lower():
            logger.warning("Concurrency limit hit [%s]: %s", request_id, exc)
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "error": {
                        "code": "SERVER_BUSY",
                        "message": str(exc),
                    },
                    "request_id": request_id,
                },
                headers={"Retry-After": "5"},
            )
        # Not a concurrency error — fall through to global handler
        return await global_exception_handler(request, exc)

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "")
        logger.error("Unhandled exception [%s]: %s", request_id, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "PROCESSING_FAILED",
                    "message": "Internal server error" if settings.is_production else str(exc),
                },
                "request_id": request_id,
            },
        )

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

    # MCP server — dual transport
    from routers.mcp_server import get_mcp_asgi_app, mcp as mcp_server

    # Streamable HTTP (MCP standard 2025-11) — primary transport
    # mcp.http_app() returns a Starlette ASGI app with /mcp endpoint
    try:
        mcp_http = mcp_server.http_app()
        app.mount("/mcp/http", mcp_http)
        logger.info("MCP Streamable HTTP mounted at /mcp/http")
    except Exception as e:
        logger.warning("MCP Streamable HTTP failed to mount: %s", e)

    # SSE transport (deprecated, kept for backwards compatibility)
    app.mount("/mcp", get_mcp_asgi_app())

    # NOTE: SSE deprecation header REMOVED — middleware breaks SSE streaming responses.
    # Deprecation will be communicated via spss_get_server_info tool response instead.

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
