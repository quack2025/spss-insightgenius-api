"""POST /v1/correlation — Correlation matrix between numeric variables."""

import asyncio
import json
import math
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth import require_scope, KeyConfig
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine, QUANTIPYMRX_AVAILABLE

router = APIRouter(tags=["Analysis"])


def _run_correlation(file_bytes: bytes, filename: str, spec: dict):
    """Run correlation analysis (blocking, executed in thread pool)."""
    data = QuantiProEngine.load_spss(file_bytes, filename)

    variables = spec.get("variables", [])
    method = spec.get("method", "pearson")
    weight = spec.get("weight")

    if len(variables) < 2:
        raise ValueError("At least 2 variables required for correlation analysis")

    for v in variables:
        if v not in data.df.columns:
            raise ValueError(f"Variable '{v}' not found in dataset")

    if not QUANTIPYMRX_AVAILABLE or data.mrx_dataset is None:
        raise RuntimeError("QuantipyMRX required for correlation analysis")

    from quantipymrx.analysis.significance import correlation_matrix

    corr_df, pval_df = correlation_matrix(data.mrx_dataset, variables=variables, method=method)

    # Convert DataFrames to serializable dicts, handling NaN
    def _clean(val):
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        return round(val, 6) if isinstance(val, float) else val

    matrix = {}
    p_values = {}
    significant_pairs = []

    for row_var in corr_df.index:
        matrix[row_var] = {col: _clean(corr_df.loc[row_var, col]) for col in corr_df.columns}
        p_values[row_var] = {col: _clean(pval_df.loc[row_var, col]) for col in pval_df.columns}

        for col_var in corr_df.columns:
            if row_var < col_var:  # upper triangle only
                p = pval_df.loc[row_var, col_var]
                r = corr_df.loc[row_var, col_var]
                if not math.isnan(p) and p < 0.05:
                    significant_pairs.append({
                        "var1": row_var, "var2": col_var,
                        "r": _clean(r), "p_value": _clean(p),
                    })

    return {
        "variables": variables,
        "method": method,
        "n_cases": len(data.df),
        "matrix": matrix,
        "p_values": p_values,
        "significant_pairs": significant_pairs,
    }


@router.post("/v1/correlation", summary="Correlation matrix",
             description="Calculate correlation matrix between 2+ numeric variables with p-values and significance flags.")
async def correlation(
    request: Request,
    file: UploadFile = File(..., description="SPSS .sav file"),
    spec: str = Form(..., description='JSON: {"variables": ["Q1","Q2","Q3"], "method": "pearson"}'),
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
        result = await run_in_executor(_run_correlation, file_bytes, file.filename or "upload.sav", spec_dict)
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
