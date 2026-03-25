"""Weight preview and RIM weight computation endpoints."""

import json
import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from auth import KeyConfig, require_auth
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Weighting"])


@router.post("/v1/weight/preview", summary="Preview variable distribution for weighting")
async def weight_preview(
    file: UploadFile = File(...),
    variable: str = Form(...),
    key: KeyConfig = Depends(require_auth),
):
    """Show current distribution of a variable — use this to decide target percentages.

    Returns counts and percentages per value, with labels from SPSS metadata.
    """
    file_bytes = await file.read()
    filename = file.filename or "upload.sav"

    def _preview():
        data = QuantiProEngine.load_spss(file_bytes, filename)
        df = data.df
        if variable not in df.columns:
            return {"error": f"Variable '{variable}' not found."}

        col = df[variable]
        n = len(df)
        n_valid = int(col.notna().sum())
        n_missing = n - n_valid

        # Get value labels from metadata
        value_labels = {}
        if data.meta and hasattr(data.meta, "variable_value_labels"):
            value_labels = data.meta.variable_value_labels.get(variable, {})

        # Get variable label
        var_label = ""
        if data.meta and hasattr(data.meta, "column_names_to_labels"):
            var_label = data.meta.column_names_to_labels.get(variable, "")

        # Build distribution
        counts = col.dropna().value_counts().sort_index()
        distribution = []
        for val, count in counts.items():
            label = value_labels.get(val, value_labels.get(int(val) if isinstance(val, float) else val, str(val)))
            pct = round((count / n_valid) * 100, 1) if n_valid > 0 else 0
            distribution.append({
                "value": str(int(val)) if isinstance(val, float) and val == int(val) else str(val),
                "label": str(label),
                "count": int(count),
                "pct": pct,
            })

        return {
            "variable": variable,
            "label": var_label,
            "total_n": n,
            "valid_n": n_valid,
            "missing_n": n_missing,
            "n_categories": len(distribution),
            "distribution": distribution,
        }

    result = await run_in_executor(_preview)

    if "error" in result:
        return JSONResponse(status_code=400, content={"success": False, "error": result})

    return {"success": True, "data": result}


@router.post("/v1/weight/compute", summary="Compute RIM weight from target distributions")
async def weight_compute(
    file: UploadFile = File(...),
    targets: str = Form(...),
    max_iterations: int = Form(50),
    max_weight: float = Form(5.0),
    key: KeyConfig = Depends(require_auth),
):
    """Compute a RIM weight (iterative proportional fitting).

    Targets is a JSON array:
    ```json
    [
      {"variable": "CLA_EDAD", "targets": {"1": 33.3, "2": 33.3, "3": 33.4}},
      {"variable": "F1", "targets": {"1": 50.0, "2": 50.0}}
    ]
    ```

    Each variable's targets must sum to ~100%.
    Returns weight statistics, convergence info, and before/after distributions.
    """
    file_bytes = await file.read()
    filename = file.filename or "upload.sav"

    try:
        targets_parsed = json.loads(targets)
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": {"code": "INVALID_JSON", "message": "targets must be valid JSON"}},
        )

    def _compute():
        from services.rim_weighter import WeightTarget, compute_rim_weight

        data = QuantiProEngine.load_spss(file_bytes, filename)

        # Build WeightTarget objects
        weight_targets = []
        for t in targets_parsed:
            wt = WeightTarget(
                variable=t["variable"],
                targets=t.get("targets", {}),
            )
            weight_targets.append(wt)

        # Add value labels to distribution output
        value_labels_map = {}
        if data.meta and hasattr(data.meta, "variable_value_labels"):
            value_labels_map = data.meta.variable_value_labels

        # Compute RIM weight
        weight_series, result = compute_rim_weight(
            df=data.df,
            targets=weight_targets,
            max_iterations=max_iterations,
            max_weight=max_weight,
        )

        # Enrich distributions with labels
        for dist in result.weighted_distributions:
            var = dist["variable"]
            vl = value_labels_map.get(var, {})
            for row in dist["before"]:
                val = row["value"]
                fval = float(val) if val.replace(".", "").replace("-", "").isdigit() else val
                row["label"] = str(vl.get(fval, vl.get(int(fval) if isinstance(fval, float) else fval, val)))
            for row in dist["after"]:
                val = row["value"]
                fval = float(val) if val.replace(".", "").replace("-", "").isdigit() else val
                row["label"] = str(vl.get(fval, vl.get(int(fval) if isinstance(fval, float) else fval, val)))

        return {
            "converged": result.converged,
            "iterations": result.iterations,
            "effective_n": result.effective_n,
            "actual_n": len(data.df),
            "efficiency": result.efficiency,
            "weight_stats": result.weight_stats,
            "weighted_distributions": result.weighted_distributions,
            "weight_column": result.weight_column,
        }

    try:
        result = await run_in_executor(_compute)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": {"code": "WEIGHTING_ERROR", "message": str(e)}},
        )

    return {"success": True, "data": result}
