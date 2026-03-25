"""Chat endpoint: conversational analysis powered by Sonnet + deterministic engine."""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, File, UploadFile
from fastapi.responses import JSONResponse

from auth import KeyConfig, require_auth
from config import get_settings
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Chat"])


@router.post("/v1/chat", summary="Conversational analysis (Sonnet + Engine)")
async def chat_endpoint(
    message: str = Form(...),
    file_id: str = Form(None),
    file: UploadFile = File(None),
    history: str = Form("[]"),
    key: KeyConfig = Depends(require_auth),
):
    """Send a natural language query about your survey data.

    Sonnet interprets the question, calls analysis tools (frequency, crosstab,
    correlation, ANOVA, tabulate), and returns insights with chart specifications.

    Either `file_id` (from /upload page) or `file` (direct upload) must be provided.
    History is a JSON array of previous messages: [{"role":"user","content":"..."},{"role":"assistant","content":"..."}]
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return JSONResponse(status_code=503, content={
            "success": False,
            "error": {"code": "AI_UNAVAILABLE", "message": "Chat requires ANTHROPIC_API_KEY"},
        })

    # Resolve file data
    file_bytes = None
    filename = "upload.sav"

    if file_id:
        # Load from Redis session
        import redis.asyncio as aioredis
        if not settings.redis_url:
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": {"code": "NO_FILE", "message": "file_id requires Redis. Upload a file directly."},
            })
        r = aioredis.from_url(settings.redis_url, decode_responses=False)
        try:
            file_bytes = await r.get(f"spss:file:{file_id}")
            meta_raw = await r.get(f"spss:meta:{file_id}")
            if meta_raw:
                meta_info = json.loads(meta_raw)
                filename = meta_info.get("filename", filename)
            # Refresh TTL
            ttl = settings.spss_session_ttl_seconds
            await r.expire(f"spss:file:{file_id}", ttl)
            await r.expire(f"spss:meta:{file_id}", ttl)
            await r.aclose()
        except Exception as e:
            try:
                await r.aclose()
            except Exception:
                pass
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": {"code": "SESSION_ERROR", "message": str(e)},
            })

        if not file_bytes:
            return JSONResponse(status_code=404, content={
                "success": False,
                "error": {"code": "FILE_NOT_FOUND", "message": f"file_id '{file_id}' not found or expired. Re-upload at /upload."},
            })

    elif file:
        file_bytes = await file.read()
        filename = file.filename or "upload.sav"
    else:
        return JSONResponse(status_code=400, content={
            "success": False,
            "error": {"code": "NO_FILE", "message": "Provide file_id or upload a file."},
        })

    # Load SPSS data
    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
    except Exception as e:
        return JSONResponse(status_code=400, content={
            "success": False,
            "error": {"code": "INVALID_FILE", "message": str(e)},
        })

    # Parse history
    try:
        history_parsed = json.loads(history) if history else []
    except json.JSONDecodeError:
        history_parsed = []

    # Run chat
    from services.chat_service import ChatService
    try:
        chat_svc = ChatService()
        result = await chat_svc.chat(
            message=message,
            data=data,
            history=history_parsed,
        )
    except Exception as e:
        logger.error("Chat error: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": {"code": "CHAT_ERROR", "message": str(e)},
        })

    return {
        "success": True,
        "data": {
            "response": result["response"],
            "charts": result["charts"],
            "downloads": result["downloads"],
            "tool_calls": result["tool_calls"],
            "model": result["model"],
        },
    }
