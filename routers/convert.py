"""POST /v1/convert — Convert SPSS file to other formats."""

import asyncio
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from auth import require_scope, KeyConfig
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine
from services.converter import FormatConverter

router = APIRouter(tags=["Conversion"])

VALID_FORMATS = {"xlsx", "csv", "dta", "parquet"}


def _validate_upload(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "No filename provided"})
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("sav", "por", "zsav"):
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": f"Unsupported format '.{ext}'. Accepted: .sav, .por, .zsav"})


@router.post("/v1/convert", summary="Convert SPSS to other formats", description="Convert .sav file to xlsx, csv, dta (Stata), or parquet format.")
async def convert(
    request: Request,
    file: UploadFile = File(..., description="SPSS .sav file"),
    target_format: str = Form(..., description="Target format: xlsx, csv, dta, parquet"),
    apply_labels: bool = Form(True, description="Replace codes with value labels in output"),
    include_metadata_sheet: bool = Form(True, description="Include variable labels sheet (Excel only)"),
    key: KeyConfig = Depends(require_scope("convert")),
):
    _validate_upload(file)

    if target_format not in VALID_FORMATS:
        raise HTTPException(400, detail={"code": "VALIDATION_ERROR", "message": f"Unsupported format '{target_format}'. Accepted: {', '.join(VALID_FORMATS)}"})

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
        output_bytes, content_type, extension = await run_in_executor(
            FormatConverter.convert, data.df, data.meta, target_format, apply_labels, include_metadata_sheet
        )
    except (asyncio.TimeoutError, RuntimeError):
        raise
    except Exception as e:
        raise HTTPException(500, detail={"code": "PROCESSING_FAILED", "message": str(e)})

    base_name = (file.filename or "data").rsplit(".", 1)[0]
    output_filename = f"{base_name}{extension}"

    return Response(
        content=output_bytes,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"',
            "X-Request-Id": getattr(request.state, "request_id", ""),
        },
    )
