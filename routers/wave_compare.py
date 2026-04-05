"""POST /v1/wave-compare — Compare two waves of the same study."""

import json
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
router = APIRouter(tags=["Analysis"])


@router.post("/v1/wave-compare", summary="Compare two waves of the same study",
             description="Upload two .sav files from the same study (different time periods) "
                         "and get deltas with significance testing.")
async def wave_compare(
    file1: UploadFile = File(None, description="Wave 1 (baseline) .sav file"),
    file1_id: str | None = Form(None, description="Wave 1 file session ID"),
    file2: UploadFile = File(None, description="Wave 2 (current) .sav file"),
    file2_id: str | None = Form(None, description="Wave 2 file session ID"),
    variables: str = Form("", description="JSON array of variable names to compare. Empty = auto-detect shared variables."),
    weight: str | None = Form(None, description="Weight variable name (must exist in both files)"),
    significance_level: float = Form(0.95, description="Confidence level for significance testing"),
    key: KeyConfig = Depends(require_scope("process")),
    _rl: None = Depends(check_rate_limit),
):
    start = time.perf_counter()

    try:
        # Load both files
        bytes1, name1 = await resolve_file(file=file1, file_id=file1_id)
        bytes2, name2 = await resolve_file(file=file2, file_id=file2_id)

        data1 = await run_in_executor(QuantiProEngine.load_spss, bytes1, name1)
        data2 = await run_in_executor(QuantiProEngine.load_spss, bytes2, name2)
    except ValueError as e:
        raise HTTPException(400, detail={"code": "LOAD_ERROR", "message": str(e)})
    except Exception as e:
        logger.error("Wave compare file load failed: %s", e, exc_info=True)
        raise HTTPException(422, detail={"code": "FILE_ERROR", "message": f"Failed to load file: {e}"})

    # Parse variables
    var_list = None
    if variables.strip():
        try:
            var_list = json.loads(variables)
        except json.JSONDecodeError:
            var_list = [v.strip() for v in variables.split(",") if v.strip()]

    # Run comparison
    try:
        from services.wave_comparison import compare_waves
        result = await run_in_executor(
            compare_waves, data1, data2, var_list, weight, significance_level,
        )
    except ValueError as e:
        raise HTTPException(400, detail={"code": "COMPARISON_ERROR", "message": str(e)})
    except Exception as e:
        logger.error("Wave compare failed: %s", e, exc_info=True)
        raise HTTPException(500, detail={"code": "COMPARISON_ERROR", "message": f"Wave comparison failed: {e}"})

    elapsed = int((time.perf_counter() - start) * 1000)
    return success_response(result, processing_time_ms=elapsed)
