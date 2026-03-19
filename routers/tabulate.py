"""POST /v1/tabulate — Full tabulation: all stubs × banner → Excel with sig letters.

The core endpoint for market research. Upload a .sav, specify a banner
(demographic) and stubs (questions), get back a professional Excel workbook
with crosstabs, significance letters, nets, and a summary sheet.
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from auth import KeyConfig, require_scope
from services.quantipy_engine import QuantiProEngine
from services.tabulation_builder import TabulateSpec, build_tabulation

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Processing"])

# Max file size per plan (bytes)
_MAX_FILE_SIZE = {
    "free": 5 * 1024 * 1024,
    "pro": 50 * 1024 * 1024,
    "business": 200 * 1024 * 1024,
}

_ALLOWED_EXTENSIONS = {".sav", ".por", ".zsav"}


@router.post(
    "/v1/tabulate",
    summary="Full tabulation → Excel",
    description=(
        "Upload a .sav file, specify a banner variable (demographic) and stub variables "
        "(questions to analyze), and receive a professional Excel workbook with:\n\n"
        "- One sheet per stub variable\n"
        "- Crosstab with column percentages\n"
        "- Significance letters (A/B/C notation)\n"
        "- Column bases (N)\n"
        "- Optional nets (Top 2 Box, Bottom 2 Box, etc.)\n"
        "- Summary sheet with column legend and stub index\n\n"
        "**Example spec:**\n```json\n{\n"
        '  "banner": "Q_4",\n'
        '  "stubs": ["Q_2", "Q_3", "Q_5"],\n'
        '  "significance_level": 0.95,\n'
        '  "weight": "WEIGHT1",\n'
        '  "nets": {"Q_2": {"Top 2 Box": [5, 6], "Bottom 2 Box": [1, 2]}},\n'
        '  "title": "Customer Satisfaction Study 2026"\n'
        "}\n```\n\n"
        "Set `stubs` to `[\"_all_\"]` to auto-select all variables with value labels."
    ),
    response_class=StreamingResponse,
)
async def tabulate(
    request: Request,
    file: UploadFile = File(..., description=".sav file to tabulate"),
    spec: str = Form(..., description="JSON tabulation specification"),
    key: KeyConfig = Depends(require_scope("process")),
):
    start = time.perf_counter()
    request_id = getattr(request.state, "request_id", "")

    # ── Validate file ──
    ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": f"Expected .sav file, got {ext}"})

    max_size = _MAX_FILE_SIZE.get(key.plan, _MAX_FILE_SIZE["free"])
    file_bytes = await file.read()
    if len(file_bytes) > max_size:
        raise HTTPException(413, detail={
            "code": "FILE_TOO_LARGE",
            "message": f"File exceeds {max_size // (1024*1024)}MB limit for {key.plan} plan",
        })

    # ── Parse spec ──
    try:
        spec_dict = json.loads(spec)
    except json.JSONDecodeError as e:
        raise HTTPException(400, detail={"code": "INVALID_SPEC", "message": f"Invalid JSON in spec: {e}"})

    banner = spec_dict.get("banner")
    if not banner:
        raise HTTPException(400, detail={"code": "INVALID_SPEC", "message": "spec.banner is required"})

    tab_spec = TabulateSpec(
        banner=banner,
        stubs=spec_dict.get("stubs", ["_all_"]),
        weight=spec_dict.get("weight"),
        significance_level=spec_dict.get("significance_level", 0.95),
        nets=spec_dict.get("nets"),
        show_counts=spec_dict.get("show_counts", True),
        show_percentages=spec_dict.get("show_percentages", True),
        title=spec_dict.get("title", ""),
    )

    # ── Load SPSS ──
    try:
        data = await asyncio.to_thread(
            QuantiProEngine.load_spss, file_bytes, file.filename or "upload.sav"
        )
    except Exception as e:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": f"Failed to load SPSS file: {e}"})

    # Validate banner exists
    if tab_spec.banner not in data.df.columns:
        raise HTTPException(400, detail={
            "code": "VARIABLE_NOT_FOUND",
            "message": f"Banner variable '{tab_spec.banner}' not found. Available: {list(data.df.columns[:20])}...",
        })

    # Validate stubs exist (if explicitly specified)
    if tab_spec.stubs != ["_all_"]:
        missing = [s for s in tab_spec.stubs if s not in data.df.columns]
        if missing:
            raise HTTPException(400, detail={
                "code": "VARIABLE_NOT_FOUND",
                "message": f"Stub variables not found: {missing}",
            })

    # ── Run tabulation ──
    try:
        result = await asyncio.to_thread(
            build_tabulation, QuantiProEngine, data, tab_spec,
        )
    except Exception as e:
        logger.error("Tabulation failed [%s]: %s", request_id, e, exc_info=True)
        raise HTTPException(500, detail={"code": "PROCESSING_FAILED", "message": str(e)})

    elapsed = int((time.perf_counter() - start) * 1000)
    logger.info(
        "[TABULATE] key=%s banner=%s stubs=%d success=%d failed=%d time_ms=%d",
        key.name, tab_spec.banner, result.total_stubs, result.successful, result.failed, elapsed,
    )

    # ── Return Excel ──
    import io
    file_name = f"tabulation_{tab_spec.banner}_{data.file_name.replace('.sav', '')}.xlsx"

    return StreamingResponse(
        io.BytesIO(result.excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "X-Request-Id": request_id,
            "X-Processing-Time-Ms": str(elapsed),
            "X-Stubs-Total": str(result.total_stubs),
            "X-Stubs-Success": str(result.successful),
            "X-Stubs-Failed": str(result.failed),
        },
    )
