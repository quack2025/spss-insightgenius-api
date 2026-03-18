"""POST /v1/frequency — Frequency table for a single variable."""

import asyncio
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth import require_scope, KeyConfig
from services.quantipy_engine import QuantiProEngine, QUANTIPYMRX_AVAILABLE

router = APIRouter(tags=["Analysis"])


def _validate_upload(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "No filename provided"})
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("sav", "por", "zsav"):
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": f"Unsupported format '.{ext}'. Accepted: .sav, .por, .zsav"})


@router.post("/v1/frequency", summary="Frequency table", description="Calculate frequency distribution for a single variable, optionally weighted.")
async def frequency(
    request: Request,
    file: UploadFile = File(..., description="SPSS .sav file"),
    variable: str = Form(..., description="Variable name to analyze"),
    weight: str | None = Form(None, description="Weight variable name"),
    key: KeyConfig = Depends(require_scope("frequency")),
):
    start = time.perf_counter()
    _validate_upload(file)

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "Empty file"})

    try:
        data = await asyncio.to_thread(QuantiProEngine.load_spss, file_bytes, file.filename or "upload.sav")
    except Exception as e:
        raise HTTPException(500, detail={"code": "PROCESSING_FAILED", "message": f"Failed to load SPSS: {e}"})

    try:
        result = await asyncio.to_thread(QuantiProEngine.frequency, data, variable, weight)
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
