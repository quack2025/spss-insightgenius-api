"""Chat endpoint: conversational analysis powered by Sonnet + deterministic engine."""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, File, UploadFile
from fastapi.responses import JSONResponse

from auth import require_auth, KeyConfig
from config import get_settings
from middleware.processing import run_in_executor
from middleware.rate_limiter import check_rate_limit
from services.quantipy_engine import QuantiProEngine
from shared.file_resolver import resolve_file

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Chat"])


@router.post("/v1/chat", summary="Conversational analysis (Sonnet + Engine)")
async def chat_endpoint(
    message: str = Form(...),
    file_id: str = Form(None),
    file: UploadFile = File(None),
    ticket: UploadFile = File(None),
    history: str = Form("[]"),
    prep_context: str = Form(""),
    key: KeyConfig = Depends(require_auth),
    _rl: None = Depends(check_rate_limit),
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
    file_bytes, filename = await resolve_file(file=file, file_id=file_id)

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

    # Parse prep context
    prep_ctx = None
    if prep_context:
        try:
            prep_ctx = json.loads(prep_context)
        except json.JSONDecodeError:
            pass

    # Parse reporting ticket if provided
    ticket_spec = None
    if ticket and ticket.filename and ticket.filename.endswith('.docx'):
        try:
            ticket_bytes = await ticket.read()
            from services.ticket_parser import TicketParser
            parser = TicketParser()
            meta = await run_in_executor(QuantiProEngine.extract_metadata, data)
            var_list = [v["name"] for v in (meta.get("variables") or [])]
            ticket_spec = await parser.parse(ticket_bytes, var_list)
            logger.info("[CHAT] Ticket parsed: %d banners, %d stubs", len(ticket_spec.get("banners", [])), len(ticket_spec.get("stubs", [])))
            # Append ticket info to message
            message += f"\n\n[SYSTEM: Reporting Ticket parsed. Spec: banners={ticket_spec.get('banners')}, stubs={ticket_spec.get('stubs')}, sig_level={ticket_spec.get('sig_level')}, nets={ticket_spec.get('nets')}. Generate the Excel tabulation using this spec.]"
        except Exception as e:
            logger.warning("[CHAT] Ticket parsing failed: %s", e)

    # Run chat
    from services.chat_service import ChatService
    try:
        chat_svc = ChatService()
        result = await chat_svc.chat(
            message=message,
            data=data,
            history=history_parsed,
            prep_context=prep_ctx,
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
