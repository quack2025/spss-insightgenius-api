"""Wave comparison — compare two datasets from the same study across time periods.

Computes deltas (Wave 2 - Wave 1) with significance testing using
independent-samples z-test for proportions and t-test for means.

Usage:
    from services.wave_comparison import compare_waves
    result = compare_waves(data_wave1, data_wave2, variables, weight=None)
"""

import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from shared.significance import z_test_proportions, t_test_means

logger = logging.getLogger(__name__)


def compare_waves(
    data1: Any,  # SPSSData (Wave 1 / baseline)
    data2: Any,  # SPSSData (Wave 2 / current)
    variables: list[str] | None = None,
    weight: str | None = None,
    significance_level: float = 0.95,
) -> dict[str, Any]:
    """Compare two waves of the same study.

    For each variable:
    - Frequencies: delta in % points + significance
    - Means: delta + t-test significance
    - NPS: delta in score + significance

    Args:
        data1: Wave 1 (baseline) SPSSData
        data2: Wave 2 (current) SPSSData
        variables: Variables to compare. None = auto-detect shared variables.
        weight: Weight variable name (must exist in both datasets).
        significance_level: Confidence level for sig testing.

    Returns:
        Dict with comparisons per variable, summary stats, and significant changes.
    """
    df1 = data1.df
    df2 = data2.df
    meta1 = data1.meta
    meta2 = data2.meta
    alpha = 1 - significance_level

    col_labels = getattr(meta2, "column_names_to_labels", {})
    value_labels_map = getattr(meta2, "variable_value_labels", {})

    # Auto-detect shared variables if not specified
    if variables is None:
        shared = set(df1.columns) & set(df2.columns)
        # Only numeric variables with value labels
        variables = [
            c for c in df2.columns
            if c in shared and c in value_labels_map and len(value_labels_map.get(c, {})) >= 2
            and pd.api.types.is_numeric_dtype(df2[c])
        ]

    n1 = len(df1)
    n2 = len(df2)
    comparisons = []
    significant_changes = []

    for var in variables:
        if var not in df1.columns or var not in df2.columns:
            continue

        vl = value_labels_map.get(var, {})
        label = col_labels.get(var, var)
        comp = {
            "variable": var,
            "label": label,
            "wave1_n": n1,
            "wave2_n": n2,
            "frequencies": {},
            "mean_delta": None,
            "sig_changes": [],
        }

        s1 = df1[var].dropna()
        s2 = df2[var].dropna()

        if len(s1) == 0 or len(s2) == 0:
            comp["error"] = "No valid data in one or both waves"
            comparisons.append(comp)
            continue

        # Frequency comparison
        all_values = sorted(set(s1.unique().tolist() + s2.unique().tolist()))
        for val in all_values:
            c1 = int((s1 == val).sum())
            c2 = int((s2 == val).sum())
            p1 = c1 / len(s1)
            p2 = c2 / len(s2)
            delta_pp = round((p2 - p1) * 100, 1)  # Delta in percentage points

            _, is_sig = z_test_proportions(
                p2, len(s2), p1, len(s1),
                alpha, n_columns=2,  # 2 columns = 2 waves
                apply_bonferroni=False,  # Only 1 comparison per value
                variable=var, col_a="Wave2", col_b="Wave1",
            )

            val_label = vl.get(val, str(val))
            comp["frequencies"][str(val)] = {
                "label": val_label,
                "wave1_pct": round(p1 * 100, 1),
                "wave2_pct": round(p2 * 100, 1),
                "delta_pp": delta_pp,
                "significant": is_sig,
                "direction": "up" if delta_pp > 0 else "down" if delta_pp < 0 else "flat",
            }

            if is_sig and abs(delta_pp) >= 2:  # Only report changes >= 2pp
                significant_changes.append({
                    "variable": var,
                    "label": label,
                    "value_label": val_label,
                    "delta_pp": delta_pp,
                    "direction": "up" if delta_pp > 0 else "down",
                })

        # Mean comparison
        if pd.api.types.is_numeric_dtype(s1):
            mean1 = float(s1.mean())
            mean2 = float(s2.mean())
            std1 = float(s1.std())
            std2 = float(s2.std())
            delta_mean = round(mean2 - mean1, 3)

            _, mean_sig = t_test_means(
                mean2, std2, len(s2),
                mean1, std1, len(s1),
                alpha, n_columns=2,
                apply_bonferroni=False,
                variable=var, col_a="Wave2", col_b="Wave1",
            )

            comp["mean_delta"] = {
                "wave1_mean": round(mean1, 2),
                "wave2_mean": round(mean2, 2),
                "delta": delta_mean,
                "significant": mean_sig,
                "direction": "up" if delta_mean > 0 else "down" if delta_mean < 0 else "flat",
            }

            if mean_sig:
                significant_changes.append({
                    "variable": var,
                    "label": label,
                    "value_label": "Mean",
                    "delta": delta_mean,
                    "direction": "up" if delta_mean > 0 else "down",
                })

        comparisons.append(comp)

    # Sort significant changes by absolute delta
    significant_changes.sort(key=lambda x: abs(x.get("delta_pp", x.get("delta", 0))), reverse=True)

    return {
        "wave1": {"file_name": data1.file_name, "n_cases": n1},
        "wave2": {"file_name": data2.file_name, "n_cases": n2},
        "variables_compared": len(comparisons),
        "significant_changes": len(significant_changes),
        "comparisons": comparisons,
        "top_changes": significant_changes[:10],
        "significance_level": significance_level,
    }
