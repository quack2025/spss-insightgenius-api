"""POST /v1/convert — Convert SPSS file to other formats."""

import asyncio
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from auth import require_scope, KeyConfig
from middleware.processing import run_in_executor
from middleware.rate_limiter import check_rate_limit
from shared.file_resolver import resolve_file
from services.quantipy_engine import QuantiProEngine
from services.converter import FormatConverter

router = APIRouter(tags=["Conversion"])

VALID_FORMATS = {"xlsx", "csv", "dta", "parquet"}


@router.post("/v1/convert", summary="Convert SPSS to other formats", description="Convert .sav file to xlsx, csv, dta (Stata), or parquet format.")
async def convert(
    request: Request,
    file: UploadFile = File(None, description="SPSS .sav file (or use file_id)"),
    file_id: str | None = Form(None, description="File session ID from /v1/library/upload"),
    target_format: str = Form(..., description="Target format: xlsx, csv, dta, parquet"),
    apply_labels: bool = Form(True, description="Replace codes with value labels in output"),
    include_metadata_sheet: bool = Form(True, description="Include variable labels sheet (Excel only)"),
    key: KeyConfig = Depends(require_scope("convert")),
    _rl: None = Depends(check_rate_limit),
):
    file_bytes, filename = await resolve_file(file=file, file_id=file_id)

    if target_format not in VALID_FORMATS:
        raise HTTPException(400, detail={"code": "VALIDATION_ERROR", "message": f"Unsupported format '{target_format}'. Accepted: {', '.join(VALID_FORMATS)}"})

    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
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

    base_name = filename.rsplit(".", 1)[0]
    output_filename = f"{base_name}{extension}"

    return Response(
        content=output_bytes,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"',
            "X-Request-Id": getattr(request.state, "request_id", ""),
        },
    )
