"""POST /v1/anova — One-way ANOVA with optional Tukey HSD post-hoc."""

import asyncio
import json
import math
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth import require_scope, KeyConfig
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine, QUANTIPYMRX_AVAILABLE

router = APIRouter(tags=["Analysis"])


def _clean(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return round(val, 6) if isinstance(val, float) else val


def _run_anova(file_bytes: bytes, filename: str, spec: dict):
    """Run ANOVA (blocking, executed in thread pool)."""
    data = QuantiProEngine.load_spss(file_bytes, filename)
    df = data.df

    dependent = spec.get("dependent", "")
    factor = spec.get("factor", "")
    weight = spec.get("weight")
    post_hoc = spec.get("post_hoc", True)

    if not dependent or not factor:
        raise ValueError("Both 'dependent' and 'factor' are required")
    for v in [dependent, factor]:
        if v not in df.columns:
            raise ValueError(f"Variable '{v}' not found in dataset")

    if not QUANTIPYMRX_AVAILABLE or data.mrx_dataset is None:
        raise RuntimeError("QuantipyMRX required for ANOVA")

    from quantipymrx.analysis.significance import anova_from_dataset

    ds = data.mrx_dataset
    result = anova_from_dataset(ds, variable=dependent, group_var=factor, weight=weight, sig_level=0.05)

    # Convert result to dict
    response = {
        "dependent": dependent,
        "factor": factor,
        "f_statistic": _clean(result.statistic),
        "p_value": _clean(result.p_value),
        "significant": result.significant,
        "df_between": None,
        "df_within": None,
        "eta_squared": None,
        "group_means": {str(k): _clean(v) for k, v in result.group_means.items()},
        "group_stds": {str(k): _clean(v) for k, v in result.group_stds.items()},
        "group_ns": {str(k): v for k, v in result.group_ns.items()},
    }

    # Extract eta-squared from details if available
    if result.details:
        response["eta_squared"] = _clean(result.details.get("eta_squared"))
        response["df_between"] = result.details.get("df_between")
        response["df_within"] = result.details.get("df_within")

    # Post-hoc Tukey HSD
    if post_hoc and result.post_hoc is not None and not result.post_hoc.empty:
        tukey_rows = []
        for _, row in result.post_hoc.iterrows():
            tukey_rows.append({
                "group1": str(row.get("group1", row.get("Group 1", ""))),
                "group2": str(row.get("group2", row.get("Group 2", ""))),
                "mean_diff": _clean(row.get("meandiff", row.get("Mean Diff", 0))),
                "p_value": _clean(row.get("p-adj", row.get("p_value", 0))),
                "significant": bool(row.get("reject", row.get("significant", False))),
            })
        response["post_hoc_tukey"] = tukey_rows
    else:
        response["post_hoc_tukey"] = []

    # Add value labels for groups
    meta = data.meta
    if meta is not None:
        vl = meta.variable_value_labels.get(factor, {})
        response["group_labels"] = {str(k): v for k, v in vl.items()} if vl else {}

    return response


@router.post("/v1/anova", summary="One-way ANOVA",
             description="Test if means of a numeric variable differ across groups, with optional Tukey HSD post-hoc comparisons.")
async def anova(
    request: Request,
    file: UploadFile = File(..., description="SPSS .sav file"),
    spec: str = Form(..., description='JSON: {"dependent": "Q1", "factor": "age_group", "post_hoc": true}'),
    key: KeyConfig = Depends(require_scope("crosstab")),
):
    start = time.perf_counter()

    try:
        spec_dict = json.loads(spec)
    except json.JSONDecodeError:
        raise HTTPException(400, detail={"code": "INVALID_SPEC", "message": "Invalid JSON in spec"})

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, detail={"code": "INVALID_FILE_FORMAT", "message": "Empty file"})

    try:
        result = await run_in_executor(_run_anova, file_bytes, file.filename or "upload.sav", spec_dict)
    except (asyncio.TimeoutError, RuntimeError) as e:
        if "QuantipyMRX required" in str(e):
            raise HTTPException(501, detail={"code": "ENGINE_UNAVAILABLE", "message": str(e)})
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
