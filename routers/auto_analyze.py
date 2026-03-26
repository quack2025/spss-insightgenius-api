"""POST /v1/auto-analyze — Zero-config SPSS analysis. Upload a .sav, get a complete Excel back."""

import asyncio
import io
import json
import logging
import time

logger = logging.getLogger(__name__)

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
    3. Detect groups (MRS, Grid, Top-of-Mind) → exclude members from individual stubs
    4. Remaining ungrouped variables → individual stubs
    5. Auto-detect nets (T2B/B2B for Likert scales)
    6. Build tabulation → return Excel bytes

    Key insight: variables that belong to a detected group (MRS, Grid, Top-of-Mind)
    are NOT exported as individual crosstabs. They're exported as their group type
    (MRS sheet or Grid summary). Only ungrouped variables get individual sheets.
    """
    # Step 1: Load and extract metadata
    data = QuantiProEngine.load_spss(file_bytes, filename)
    meta = QuantiProEngine.extract_metadata(data)

    # Step 2: Pick banners
    suggested = meta.get("suggested_banners") or []
    max_banners = options.get("max_banners", 3)
    if suggested:
        banners = [b["variable"] for b in suggested[:max_banners]]
    else:
        banners = []
        for v in meta.get("variables", []):
            vl = v.get("value_labels")
            if vl and 2 <= len(vl) <= 8 and v["name"] not in banners:
                banners.append(v["name"])
                if len(banners) >= max_banners:
                    break

    if not banners:
        raise ValueError("No suitable banner variables found in the dataset")

    banner_set = set(banners)

    # Step 3: Detect groups and collect grouped variables
    mrs_groups = {}
    grid_groups = {}
    grouped_vars = set()  # Track ALL variables that belong to a group

    detected_groups = meta.get("detected_groups") or []
    for g in detected_groups:
        q_type = g.get("question_type", "")
        members = g.get("variables") or []
        if len(members) < 2:
            continue

        name = g.get("display_name") or g.get("name", f"Group_{len(grouped_vars)}")

        if q_type in ("awareness", "top_of_mind"):
            # MRS: "select all that apply" — one sheet, members as rows, % can exceed 100%
            mrs_groups[name] = members
            grouped_vars.update(members)
        elif q_type == "scale":
            # Grid: same scale across variables — compact T2B/Mean summary
            grid_groups[name] = {"variables": members, "show": ["t2b", "b2b", "mean"]}
            grouped_vars.update(members)

    # Step 4: Build stubs — only UNGROUPED variables with value labels
    # Variables in groups are exported via MRS/Grid, not as individual crosstabs
    stubs = []
    for v in meta.get("variables") or []:
        vname = v["name"]
        vl = v.get("value_labels")
        if not vl or len(vl) < 2:
            continue
        if vname in grouped_vars:
            continue  # Skip — this variable is in an MRS or Grid group
        if vname in banner_set:
            continue  # Skip — this is a banner variable
        stubs.append(vname)

    if not stubs and not mrs_groups and not grid_groups:
        stubs = ["_all_"]  # Fallback: export everything if nothing detected

    # Step 5: Auto-nets from preset_nets (only for ungrouped stubs)
    all_nets = meta.get("preset_nets") or {}
    nets = {k: v for k, v in all_nets.items() if k in set(stubs)}

    # Step 6: Build spec
    spec = TabulateSpec(
        banners=banners,
        stubs=stubs if stubs else ["_all_"],
        significance_level=options.get("significance_level", 0.95),
        include_means=True,
        include_total_column=True,
        output_mode=options.get("output_mode", "multi_sheet"),
        title=options.get("title", f"Auto-Analysis: {filename}"),
        nets=nets or {},
        mrs_groups=mrs_groups or {},
        grid_groups=grid_groups or {},
    )

    logger.info(
        "[AUTO] banners=%s stubs=%d mrs=%d(%d vars) grids=%d(%d vars) nets=%d grouped_excluded=%d",
        banners, len(stubs), len(mrs_groups), sum(len(v) for v in mrs_groups.values()),
        len(grid_groups), sum(len(g["variables"]) for g in grid_groups.values()),
        len(nets), len(grouped_vars),
    )

    # Step 7: Build tabulation
    result = build_tabulation(QuantiProEngine, data, spec)

    # Build sheet summaries for executive summary
    sheet_summaries = []
    for s in result.sheets:
        if s.status != "success":
            continue
        entry = {"variable": s.variable, "label": s.label, "status": s.status}
        first_ct = list((s.crosstab_data or {}).values())[0] if s.crosstab_data else {}
        sig_cells = []
        for row in first_ct.get("table", []):
            for k, v in row.items():
                if isinstance(v, dict) and v.get("significance_letters"):
                    sig_cells.append(f"{row.get('row_label','?')}:{k} {v['percentage']}% ({','.join(v['significance_letters'])})")
        entry["significant_cells"] = sig_cells[:5]
        sheet_summaries.append(entry)

    return {
        "excel_bytes": result.excel_bytes,
        "filename": f"auto_analysis_{filename.replace('.sav', '')}.xlsx",
        "_tabulation_result": result,
        "_spec": spec,
        "_data": data,
        "sheet_summaries": sheet_summaries,
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
            "n_cases": meta.get("n_cases", 0),
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
    excel_bytes = result["excel_bytes"]

    # Executive Summary (#5) — add AI summary as first sheet if requested
    include_summary = options_dict.get("include_summary", True)  # Default ON for auto-analyze
    if include_summary:
        try:
            from services.executive_summary import generate_executive_summary
            summary_text = await generate_executive_summary(
                tabulation_results=result.get("sheet_summaries", []),
                banner_labels=summary.get("banner_labels", []),
                study_context=options_dict.get("study_context"),
                file_name=result["filename"],
                n_cases=summary.get("n_cases", 0),
            )
            if summary_text:
                # Rebuild Excel with summary sheet prepended
                from services.tabulation_builder import _build_excel
                tab_result = result.get("_tabulation_result")
                if tab_result:
                    tab_result.executive_summary = summary_text
                    excel_bytes = _build_excel(tab_result, result.get("_spec"), result.get("_data"))
                    logger.info("[AUTO] Executive summary added (%d chars)", len(summary_text))
        except Exception as e:
            logger.warning("[AUTO] Executive summary failed (non-blocking): %s", e)

    return StreamingResponse(
        io.BytesIO(excel_bytes),
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
