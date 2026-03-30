"""POST /v1/smart-spec — AI generates complete tabulation spec from .sav + questionnaire + ticket."""

import time
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from auth import require_scope, KeyConfig
from middleware.processing import run_in_executor
from middleware.rate_limiter import check_rate_limit
from services.quantipy_engine import QuantiProEngine
from shared.file_resolver import resolve_file
from shared.response import success_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["AI Features"])


@router.post("/v1/smart-spec", summary="AI-generated tabulation spec",
             description="Upload .sav + questionnaire (.docx/.pdf) + reporting ticket (.docx) → "
                         "Sonnet generates a complete tabulation spec with confidence levels.")
async def smart_spec(
    file: UploadFile = File(None, description="SPSS .sav file"),
    file_id: str | None = Form(None, description="File session ID"),
    questionnaire: UploadFile = File(None, description="Questionnaire .docx or .pdf"),
    ticket: UploadFile = File(None, description="Reporting Ticket .docx"),
    key: KeyConfig = Depends(require_scope("process")),
    _rl: None = Depends(check_rate_limit),
):
    start = time.perf_counter()
    settings = __import__("config").get_settings()

    if not settings.anthropic_api_key:
        raise HTTPException(503, detail={"code": "AI_UNAVAILABLE", "message": "ANTHROPIC_API_KEY required"})

    # Load SPSS metadata
    file_bytes, filename = await resolve_file(file=file, file_id=file_id)
    data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
    metadata = await run_in_executor(QuantiProEngine.extract_metadata, data)

    # Extract questionnaire text
    from services.smart_spec_generator import SmartSpecGenerator
    questionnaire_text = None
    if questionnaire and questionnaire.filename:
        q_bytes = await questionnaire.read()
        if q_bytes:
            questionnaire_text = SmartSpecGenerator.extract_document_text(q_bytes, questionnaire.filename)
            logger.info("[SMART_SPEC] Questionnaire: %s (%d chars)", questionnaire.filename, len(questionnaire_text))

    # Extract ticket text
    ticket_text = None
    if ticket and ticket.filename:
        t_bytes = await ticket.read()
        if t_bytes:
            ticket_text = SmartSpecGenerator.extract_document_text(t_bytes, ticket.filename)
            logger.info("[SMART_SPEC] Ticket: %s (%d chars)", ticket.filename, len(ticket_text))

    if not questionnaire_text and not ticket_text:
        raise HTTPException(400, detail={
            "code": "NO_DOCUMENTS",
            "message": "Provide at least a questionnaire (.docx/.pdf) or reporting ticket (.docx). "
                       "Both are recommended for best results.",
        })

    # Generate spec
    generator = SmartSpecGenerator()
    spec = await generator.generate(
        metadata=metadata,
        questionnaire_text=questionnaire_text,
        ticket_text=ticket_text,
    )

    elapsed = int((time.perf_counter() - start) * 1000)
    return success_response(spec, processing_time_ms=elapsed)
