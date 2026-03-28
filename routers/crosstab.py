"""POST /v1/crosstab — Crosstab with significance testing."""

import asyncio
import json
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth import require_scope, KeyConfig
from middleware.processing import run_in_executor
from middleware.rate_limiter import check_rate_limit
from shared.file_resolver import resolve_file
from shared.response import success_response
from services.quantipy_engine import QuantiProEngine, QUANTIPYMRX_AVAILABLE

router = APIRouter(tags=["Analysis"])


@router.post("/v1/crosstab", summary="Crosstab with significance", description="Cross-tabulation with column proportion z-test significance letters (A/B/C notation).")
async def crosstab(
    request: Request,
    file: UploadFile = File(None, description="SPSS .sav file (or use file_id)"),
    file_id: str | None = Form(None, description="File session ID from /v1/library/upload"),
    spec: str = Form(..., description='JSON object: {"row": "Q1", "col": "S2", "weight": null, "significance_level": 0.95}'),
    key: KeyConfig = Depends(require_scope("crosstab")),
    _rl: None = Depends(check_rate_limit),
):
    start = time.perf_counter()

    file_bytes, filename = await resolve_file(file=file, file_id=file_id)

    # Parse spec JSON
    try:
        spec_data = json.loads(spec)
    except json.JSONDecodeError:
        raise HTTPException(400, detail={"code": "VALIDATION_ERROR", "message": "Invalid JSON in 'spec' field"})

    row_var = spec_data.get("row")
    col_var = spec_data.get("col")
    if not row_var or not col_var:
        raise HTTPException(400, detail={"code": "VALIDATION_ERROR", "message": "'row' and 'col' are required in spec"})

    weight = spec_data.get("weight")
    sig_level = spec_data.get("significance_level", 0.95)

    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
    except (asyncio.TimeoutError, RuntimeError):
        raise
    except Exception as e:
        raise HTTPException(500, detail={"code": "PROCESSING_FAILED", "message": f"Failed to load SPSS: {e}"})

    try:
        result = await run_in_executor(
            QuantiProEngine.crosstab_with_significance, data, row_var, col_var, weight, sig_level
        )
    except (asyncio.TimeoutError, RuntimeError):
        raise
    except ValueError as e:
        raise HTTPException(400, detail={"code": "VARIABLE_NOT_FOUND", "message": str(e)})
    except Exception as e:
        raise HTTPException(500, detail={"code": "PROCESSING_FAILED", "message": str(e)})

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return success_response(result, processing_time_ms=elapsed_ms, meta={
        "engine_version": "1.0.0",
        "quantipymrx_available": QUANTIPYMRX_AVAILABLE,
    })
