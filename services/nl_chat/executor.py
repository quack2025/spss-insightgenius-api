"""Analysis Executor — runs analysis plans against quantipy_engine.

Takes the analysis plan from the interpreter and executes each request
by calling QuantiProEngine methods DIRECTLY. No adapter layer.

Includes fuzzy variable resolution to handle typos and accent differences.
"""

import asyncio
import logging
import unicodedata
from typing import Any

from services.quantipy_engine import QuantiProEngine, SPSSData

logger = logging.getLogger(__name__)

# Low base threshold (configurable per project in later phases)
DEFAULT_LOW_BASE_THRESHOLD = 20


async def execute_analysis_plan(
    data: SPSSData,
    plan: list[dict[str, Any]],
    low_base_threshold: int = DEFAULT_LOW_BASE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Execute a list of analysis requests against the quantipy_engine.

    Returns a list of results, one per request.
    Each result has: type, variable, success, result, warnings, error.
    """
    results = []

    for request in plan:
        result = await asyncio.to_thread(
            _execute_single, data, request, low_base_threshold
        )
        results.append(result)

    return results


def _execute_single(
    data: SPSSData,
    request: dict[str, Any],
    low_base_threshold: int,
) -> dict[str, Any]:
    """Execute a single analysis request (blocking, runs in thread)."""
    analysis_type = request.get("type", "frequency")
    variable = request.get("variable")
    cross_variable = request.get("cross_variable")
    weight = request.get("weight")
    sig_level = request.get("significance_level", 0.95)
    warnings = []

    # Resolve variables (fuzzy matching)
    if variable:
        resolved = _fuzzy_resolve(variable, data.df.columns.tolist(), data.meta)
        if resolved != variable:
            warnings.append(f"Resolved '{variable}' → '{resolved}'")
            variable = resolved

    if cross_variable:
        resolved = _fuzzy_resolve(cross_variable, data.df.columns.tolist(), data.meta)
        if resolved != cross_variable:
            warnings.append(f"Resolved '{cross_variable}' → '{resolved}'")
            cross_variable = resolved

    if weight:
        resolved = _fuzzy_resolve(weight, data.df.columns.tolist(), data.meta)
        if resolved != weight:
            weight = resolved

    # Validate variable exists
    if variable and variable not in data.df.columns:
        return _error_result(analysis_type, variable, f"Variable '{variable}' not found in dataset")

    if cross_variable and cross_variable not in data.df.columns:
        return _error_result(analysis_type, variable, f"Variable '{cross_variable}' not found")

    # Check low base
    if variable:
        n_valid = data.df[variable].notna().sum()
        if n_valid < low_base_threshold:
            warnings.append(f"Low base warning: '{variable}' has only {n_valid} valid cases (threshold: {low_base_threshold})")

    try:
        result = _dispatch(data, analysis_type, variable, cross_variable, weight, sig_level, request)
        return {
            "type": analysis_type,
            "variable": variable,
            "cross_variable": cross_variable,
            "success": True,
            "result": result,
            "warnings": warnings,
            "error": None,
        }
    except Exception as e:
        logger.error("Analysis %s failed for %s: %s", analysis_type, variable, e)
        return _error_result(analysis_type, variable, str(e), warnings=warnings)


def _dispatch(
    data: SPSSData,
    analysis_type: str,
    variable: str | None,
    cross_variable: str | None,
    weight: str | None,
    sig_level: float,
    request: dict,
) -> dict[str, Any]:
    """Route analysis type to the correct quantipy_engine method."""

    if analysis_type == "frequency":
        if not variable:
            raise ValueError("Variable required for frequency analysis")
        return QuantiProEngine.frequency(data, variable, weight=weight)

    elif analysis_type in ("crosstab", "crosstab_with_significance"):
        if not variable or not cross_variable:
            raise ValueError("Both row and column variables required for crosstab")
        return QuantiProEngine.crosstab_with_significance(
            data, row=variable, col=cross_variable,
            weight=weight, significance_level=sig_level,
        )

    elif analysis_type == "compare_means":
        # Use crosstab with mean calculation
        if not variable or not cross_variable:
            raise ValueError("Dependent variable and grouping variable required")
        return QuantiProEngine.crosstab_with_significance(
            data, row=variable, col=cross_variable, weight=weight,
            significance_level=sig_level,
        )

    elif analysis_type == "nps":
        if not variable:
            raise ValueError("Variable required for NPS calculation")
        return QuantiProEngine.nps(data, variable, weight=weight)

    elif analysis_type == "net_score":
        if not variable:
            raise ValueError("Variable required for net score")
        top_codes = request.get("top_box_codes", [4, 5])
        bottom_codes = request.get("bottom_box_codes", [1, 2])
        return QuantiProEngine.top_bottom_box(
            data, variable, top_codes=top_codes, bottom_codes=bottom_codes, weight=weight,
        )

    elif analysis_type == "correlation":
        # Correlation uses the router's inline logic — we replicate here
        variables = request.get("variables", [])
        if not variables and variable:
            variables = [variable]
            if cross_variable:
                variables.append(cross_variable)
        if len(variables) < 2:
            raise ValueError("At least 2 variables required for correlation")
        return _run_correlation(data, variables, weight)

    elif analysis_type == "descriptive":
        if not variable:
            raise ValueError("Variable required for descriptive stats")
        return _run_descriptive(data, variable, weight)

    elif analysis_type == "multiple_response":
        if not variable:
            raise ValueError("Variable or group required for MRS analysis")
        # Try to find MRS group members
        prefix = variable.rsplit("_", 1)[0] if "_" in variable else variable
        mrs_vars = [c for c in data.df.columns if c.startswith(prefix)]
        if len(mrs_vars) < 2:
            mrs_vars = [variable]
        results = {}
        for v in mrs_vars:
            if v in data.df.columns:
                freq = QuantiProEngine.frequency(data, v, weight=weight)
                results[v] = freq
        return {"type": "multiple_response", "variables": mrs_vars, "results": results}

    elif analysis_type == "gap_analysis":
        # Gap analysis needs importance + performance variable pairs
        importance_vars = request.get("importance_vars", [])
        performance_vars = request.get("performance_vars", [])
        if not importance_vars or not performance_vars:
            raise ValueError("Importance and performance variables required for gap analysis")
        return _run_gap_analysis(data, importance_vars, performance_vars, weight)

    elif analysis_type in ("executive_summary", "detailed_report"):
        # These are handled at the router level (need Claude for narrative)
        return {"type": analysis_type, "note": "Handled by router"}

    else:
        raise ValueError(f"Unknown analysis type: {analysis_type}")


# ─── Fuzzy Variable Resolution ───────────────────────────────────────────


def _fuzzy_resolve(name: str, columns: list[str], meta: Any) -> str:
    """Resolve a variable name with 5 strategies: exact, case, accent, label, substring."""

    # 1. Exact match
    if name in columns:
        return name

    # 2. Case-insensitive
    lower_map = {c.lower(): c for c in columns}
    if name.lower() in lower_map:
        return lower_map[name.lower()]

    # 3. Accent-insensitive
    def _strip_accents(s: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        )

    stripped_map = {_strip_accents(c.lower()): c for c in columns}
    if _strip_accents(name.lower()) in stripped_map:
        return stripped_map[_strip_accents(name.lower())]

    # 4. Label match (search variable labels)
    col_labels = getattr(meta, "column_names_to_labels", {})
    for col, label in col_labels.items():
        if label and name.lower() in label.lower():
            return col

    # 5. Substring match
    for col in columns:
        if name.lower() in col.lower() or col.lower() in name.lower():
            return col

    # No match — return original (will fail downstream with clear error)
    return name


# ─── Analysis Implementations ────────────────────────────────────────────


def _run_correlation(data: SPSSData, variables: list[str], weight: str | None) -> dict:
    """Run correlation matrix using scipy."""
    import numpy as np
    from scipy import stats

    df = data.df[variables].dropna()
    n = len(df)
    if n < 3:
        raise ValueError(f"Not enough data for correlation (n={n})")

    matrix = {}
    p_values = {}
    for i, v1 in enumerate(variables):
        matrix[v1] = {}
        p_values[v1] = {}
        for j, v2 in enumerate(variables):
            if i == j:
                matrix[v1][v2] = 1.0
                p_values[v1][v2] = 0.0
            else:
                r, p = stats.pearsonr(df[v1], df[v2])
                matrix[v1][v2] = round(float(r), 4)
                p_values[v1][v2] = round(float(p), 4)

    return {"matrix": matrix, "p_values": p_values, "n": n, "variables": variables}


def _run_descriptive(data: SPSSData, variable: str, weight: str | None) -> dict:
    """Run descriptive statistics."""
    import numpy as np
    series = data.df[variable].dropna()

    if weight and weight in data.df.columns:
        w = data.df.loc[series.index, weight]
        mean = float(np.average(series, weights=w))
    else:
        mean = float(series.mean())

    return {
        "variable": variable,
        "n": int(len(series)),
        "mean": round(mean, 4),
        "std": round(float(series.std()), 4),
        "median": round(float(series.median()), 4),
        "min": round(float(series.min()), 4),
        "max": round(float(series.max()), 4),
        "skewness": round(float(series.skew()), 4),
        "kurtosis": round(float(series.kurtosis()), 4),
    }


def _run_gap_analysis(
    data: SPSSData,
    importance_vars: list[str],
    performance_vars: list[str],
    weight: str | None,
) -> dict:
    """Run importance-performance gap analysis."""
    import numpy as np
    df = data.df
    items = []

    for imp_var, perf_var in zip(importance_vars, performance_vars):
        if imp_var not in df.columns or perf_var not in df.columns:
            continue
        valid = df[[imp_var, perf_var]].dropna()
        if len(valid) < 3:
            continue

        if weight and weight in df.columns:
            w = df.loc[valid.index, weight]
            imp_mean = float(np.average(valid[imp_var], weights=w))
            perf_mean = float(np.average(valid[perf_var], weights=w))
        else:
            imp_mean = float(valid[imp_var].mean())
            perf_mean = float(valid[perf_var].mean())

        items.append({
            "importance_variable": imp_var,
            "performance_variable": perf_var,
            "importance_mean": round(imp_mean, 4),
            "performance_mean": round(perf_mean, 4),
            "gap": round(imp_mean - perf_mean, 4),
            "n": int(len(valid)),
        })

    return {"items": items, "n_items": len(items)}


# ─── Helpers ──────────────────────────────────────────────────────────────


def _error_result(
    analysis_type: str,
    variable: str | None,
    error: str,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "type": analysis_type,
        "variable": variable,
        "cross_variable": None,
        "success": False,
        "result": None,
        "warnings": warnings or [],
        "error": error,
    }
