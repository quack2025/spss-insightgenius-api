"""POST /v1/parse-ticket — Parse a Reporting Ticket .docx via Claude Sonnet.

When a .sav file is also provided, Sonnet matches ticket variable references
to actual dataset variables using labels and fuzzy matching.
"""

import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth import require_scope, KeyConfig
from config import get_settings
from middleware.processing import run_in_executor
from middleware.rate_limiter import check_rate_limit
from services.quantipy_engine import QuantiProEngine
from shared.file_resolver import resolve_file
from shared.response import success_response

router = APIRouter(tags=["AI Features"])


@router.post("/v1/parse-ticket", summary="Parse Reporting Ticket",
             description="Parse a Reporting Ticket (.docx) into a TabulateSpec-compatible plan. "
                         "Optionally provide a .sav file for intelligent variable matching.")
async def parse_ticket(
    request: Request,
    ticket: UploadFile = File(..., description="Reporting Ticket .docx file"),
    file: UploadFile = File(None, description="SPSS .sav file for variable matching (optional)"),
    file_id: str | None = Form(None, description="File session ID for variable matching (optional)"),
    key: KeyConfig = Depends(require_scope("parse_ticket")),
    _rl: None = Depends(check_rate_limit),
):
    start = time.perf_counter()

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(503, detail={
            "code": "PROCESSING_FAILED",
            "message": "AI features disabled (ANTHROPIC_API_KEY not configured)",
        })

    if not ticket.filename or not ticket.filename.lower().endswith((".docx", ".doc")):
        raise HTTPException(400, detail={
            "code": "INVALID_TICKET",
            "message": "File must be a .docx document",
        })

    ticket_bytes = await ticket.read()
    if not ticket_bytes:
        raise HTTPException(400, detail={
            "code": "INVALID_TICKET",
            "message": "Empty file",
        })

    # Get variable list from .sav if provided (for intelligent matching)
    available_variables = None
    if file_id or (file and file.filename):
        try:
            file_bytes, filename = await resolve_file(file=file, file_id=file_id)
            data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
            meta = await run_in_executor(QuantiProEngine.extract_metadata, data)
            available_variables = meta.get("variables", [])
        except Exception as e:
            # Non-blocking — parse ticket without variable matching
            pass

    try:
        from services.ticket_parser import TicketParser
        parser = TicketParser()
        result = await parser.parse(ticket_bytes, available_variables)
    except Exception as e:
        raise HTTPException(500, detail={
            "code": "INVALID_TICKET",
            "message": f"Failed to parse ticket: {e}",
        })

    return success_response(result, processing_time_ms=int((time.perf_counter() - start) * 1000))
