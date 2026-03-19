"""QuantiPro API — SPSS processing microservice powered by QuantipyMRX + Haiku."""

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

    yield
    logger.info("Shutting down %s", settings.app_name)


def create_application() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "**QuantiPro API** — REST API for processing SPSS (.sav) files.\n\n"
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

    app.include_router(health_router)
    app.include_router(metadata_router)
    app.include_router(frequency_router)
    app.include_router(crosstab_router)
    app.include_router(convert_router)
    app.include_router(parse_ticket_router)
    app.include_router(process_router)
    app.include_router(tabulate_router)

    # Serve frontend
    public_dir = Path(__file__).parent / "public"
    if public_dir.exists():
        @app.get("/", include_in_schema=False)
        async def root():
            return FileResponse(public_dir / "index.html")

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
