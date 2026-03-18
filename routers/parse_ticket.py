"""POST /v1/parse-ticket — Parse a Reporting Ticket .docx via Haiku."""

import asyncio
import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from auth import require_scope, KeyConfig
from config import get_settings
from services.quantipy_engine import QUANTIPYMRX_AVAILABLE

router = APIRouter(tags=["AI Features"])


@router.post("/v1/parse-ticket", summary="Parse Reporting Ticket", description="Parse a market research Reporting Ticket (.docx) into a structured analysis plan using Claude Haiku.")
async def parse_ticket(
    request: Request,
    ticket: UploadFile = File(..., description="Reporting Ticket .docx file"),
    key: KeyConfig = Depends(require_scope("parse_ticket")),
):
    start = time.perf_counter()

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(503, detail={"code": "PROCESSING_FAILED", "message": "Haiku features are disabled (ANTHROPIC_API_KEY not configured)"})

    if not ticket.filename or not ticket.filename.lower().endswith((".docx", ".doc")):
        raise HTTPException(400, detail={"code": "INVALID_TICKET", "message": "File must be a .docx document"})

    ticket_bytes = await ticket.read()
    if not ticket_bytes:
        raise HTTPException(400, detail={"code": "INVALID_TICKET", "message": "Empty file"})

    try:
        from services.ticket_parser import TicketParser
        parser = TicketParser()
        result = await parser.parse(ticket_bytes)
    except ImportError:
        raise HTTPException(503, detail={"code": "PROCESSING_FAILED", "message": "Ticket parser not available"})
    except Exception as e:
        raise HTTPException(500, detail={"code": "INVALID_TICKET", "message": f"Failed to parse ticket: {e}"})

    return {
        "success": True,
        "data": result,
        "meta": {
            "request_id": getattr(request.state, "request_id", ""),
            "processing_time_ms": int((time.perf_counter() - start) * 1000),
            "engine_version": "1.0.0",
            "quantipymrx_available": QUANTIPYMRX_AVAILABLE,
        },
    }
