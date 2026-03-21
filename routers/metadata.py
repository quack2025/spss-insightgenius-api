"""POST /v1/metadata — Extract variable metadata from an SPSS file."""

import asyncio
import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from auth import require_scope, KeyConfig
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine, QUANTIPYMRX_AVAILABLE

router = APIRouter(tags=["Metadata"])


def _validate_upload(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "No filename provided"})
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("sav", "por", "zsav"):
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": f"Unsupported format '.{ext}'. Accepted: .sav, .por, .zsav"})


@router.post("/v1/metadata", summary="Extract SPSS file metadata", description="Returns variable names, labels, types, value labels, and auto-detected question types. No analysis is performed.")
async def metadata(
    request: Request,
    file: UploadFile = File(..., description="SPSS .sav file"),
    key: KeyConfig = Depends(require_scope("metadata")),
):
    start = time.perf_counter()
    _validate_upload(file)

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "Empty file"})

    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, file.filename or "upload.sav")
        result = await run_in_executor(QuantiProEngine.extract_metadata, data)
    except (asyncio.TimeoutError, RuntimeError):
        raise  # handled by global exception handlers (504 / 503)
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
