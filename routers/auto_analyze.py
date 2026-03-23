"""POST /v1/auto-analyze — Zero-config SPSS analysis. Upload a .sav, get a complete Excel back."""

import asyncio
import io
import json
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from auth import require_scope, KeyConfig
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine, QUANTIPYMRX_AVAILABLE
from services.tabulation_builder import TabulateSpec, build_tabulation

router = APIRouter(tags=["Processing"])


def _run_auto_analyze(file_bytes: bytes, filename: str, options: dict):
    """Zero-config analysis pipeline:
    1. Load SPSS → extract metadata with auto-detect
    2. Pick best banner(s) from suggested_banners
    3. Select all labeled variables as stubs
    4. Auto-detect nets (T2B/B2B for Likert scales)
    5. Build tabulation → return Excel bytes
    """
    # Step 1: Load and extract metadata
    data = QuantiProEngine.load_spss(file_bytes, filename)
    meta = QuantiProEngine.extract_metadata(data)

    # Step 2: Pick banners
    suggested = meta.get("suggested_banners", [])
    max_banners = options.get("max_banners", 3)
    if suggested:
        banners = [b["variable"] for b in suggested[:max_banners]]
    else:
        # Fallback: find variables with 2-8 categories (likely demographics)
        banners = []
        for v in meta.get("variables", []):
            vl = v.get("value_labels")
            if vl and 2 <= len(vl) <= 8 and v["name"] not in banners:
                banners.append(v["name"])
                if len(banners) >= max_banners:
                    break

    if not banners:
        raise ValueError("No suitable banner variables found in the dataset")

    # Step 3: Auto-stubs
    stubs = ["_all_"]

    # Step 4: Auto-nets from preset_nets
    nets = meta.get("preset_nets", {})

    # Step 5: Detect MRS groups
    mrs_groups = {}
    detected_groups = meta.get("detected_groups", [])
    for g in detected_groups:
        if g.get("question_type") == "awareness" and len(g.get("variables", [])) >= 2:
            name = g.get("display_name") or g.get("name", "MRS")
            mrs_groups[name] = g["variables"]

    # Step 6: Detect grid groups
    grid_groups = {}
    for g in detected_groups:
        if g.get("question_type") == "scale" and len(g.get("variables", [])) >= 2:
            name = g.get("display_name") or g.get("name", "Grid")
            grid_groups[name] = {"variables": g["variables"], "show": ["t2b", "b2b", "mean"]}

    # Step 7: Build spec
    spec = TabulateSpec(
        banners=banners,
        stubs=stubs,
        significance_level=options.get("significance_level", 0.95),
        include_means=True,
        include_total_column=True,
        output_mode=options.get("output_mode", "multi_sheet"),
        title=options.get("title", f"Auto-Analysis: {filename}"),
        nets=nets or {},
        mrs_groups=mrs_groups or {},
        grid_groups=grid_groups or {},
    )

    # Step 8: Build tabulation
    result = build_tabulation(QuantiProEngine, data, spec)

    return {
        "excel_bytes": result.excel_bytes,
        "filename": f"auto_analysis_{filename.replace('.sav', '')}.xlsx",
        "summary": {
            "banners": banners,
            "banner_labels": [
                next((v.get("label", v["name"]) for v in meta["variables"] if v["name"] == b), b)
                for b in banners
            ],
            "total_stubs": result.total_stubs,
            "stubs_success": result.successful,
            "stubs_failed": result.failed,
            "mrs_groups": len(mrs_groups),
            "grid_groups": len(grid_groups),
            "nets_applied": len(nets),
            "processing_time_ms": 0,
        },
    }


@router.post("/v1/auto-analyze", summary="Zero-config auto analysis",
             description="Upload a .sav file and get a complete Excel workbook with auto-detected banners, "
                         "stubs, nets, MRS groups, and significance testing. No configuration needed.")
async def auto_analyze(
    request: Request,
    file: UploadFile = File(..., description="SPSS .sav file"),
    options: str = Form("{}", description='Optional JSON: {"max_banners": 3, "output_mode": "multi_sheet", "significance_level": 0.95}'),
    key: KeyConfig = Depends(require_scope("process")),
):
    start = time.perf_counter()

    try:
        options_dict = json.loads(options)
    except json.JSONDecodeError:
        options_dict = {}

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "Empty file"})

    try:
        result = await run_in_executor(_run_auto_analyze, file_bytes, file.filename or "upload.sav", options_dict)
    except (asyncio.TimeoutError, RuntimeError):
        raise
    except ValueError as e:
        raise HTTPException(400, detail={"code": "PROCESSING_FAILED", "message": str(e)})
    except Exception as e:
        import traceback
        logger.error("Auto-analyze failed: %s\n%s", e, traceback.format_exc())
        raise HTTPException(500, detail={"code": "PROCESSING_FAILED", "message": str(e)})

    elapsed = int((time.perf_counter() - start) * 1000)
    summary = result["summary"]

    return StreamingResponse(
        io.BytesIO(result["excel_bytes"]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{result["filename"]}"',
            "X-Processing-Time-Ms": str(elapsed),
            "X-Stubs-Total": str(summary["total_stubs"]),
            "X-Stubs-Success": str(summary["stubs_success"]),
            "X-Stubs-Failed": str(summary["stubs_failed"]),
            "X-Banners": ",".join(summary["banners"]),
            "X-MRS-Groups": str(summary["mrs_groups"]),
            "X-Grid-Groups": str(summary["grid_groups"]),
            "X-Nets-Applied": str(summary["nets_applied"]),
        },
    )
