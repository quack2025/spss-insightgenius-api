"""POST /v1/crosstab — Crosstab with significance testing."""

import asyncio
import json
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth import require_scope, KeyConfig
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine, QUANTIPYMRX_AVAILABLE

router = APIRouter(tags=["Analysis"])


def _validate_upload(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "No filename provided"})
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("sav", "por", "zsav"):
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": f"Unsupported format '.{ext}'. Accepted: .sav, .por, .zsav"})


@router.post("/v1/crosstab", summary="Crosstab with significance", description="Cross-tabulation with column proportion z-test significance letters (A/B/C notation).")
async def crosstab(
    request: Request,
    file: UploadFile = File(..., description="SPSS .sav file"),
    spec: str = Form(..., description='JSON object: {"row": "Q1", "col": "S2", "weight": null, "significance_level": 0.95}'),
    key: KeyConfig = Depends(require_scope("crosstab")),
):
    start = time.perf_counter()
    _validate_upload(file)

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

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "Empty file"})

    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, file.filename or "upload.sav")
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
