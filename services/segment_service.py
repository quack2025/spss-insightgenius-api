"""Segment Service — resolves segment conditions into DataFrame filters."""

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def resolve_segment_filter(df: pd.DataFrame, conditions: list[dict[str, Any]]) -> pd.DataFrame:
    """Apply segment conditions to filter a DataFrame.

    Conditions are AND groups: all groups must match.
    Within a group, conditions are AND (all must match).

    Format: [{"group": [{"variable": "X", "operator": "in", "values": [1,2]}]}]
    """
    if not conditions:
        return df

    result = df
    for group in conditions:
        group_conditions = group.get("group", [])
        if not group_conditions:
            continue

        mask = pd.Series(True, index=result.index)
        for cond in group_conditions:
            variable = cond.get("variable", "")
            operator = cond.get("operator", "in")
            values = cond.get("values", [])
            value = cond.get("value")

            if variable not in result.columns:
                continue

            if operator == "in":
                mask = mask & result[variable].isin(values)
            elif operator == "not_in":
                mask = mask & ~result[variable].isin(values)
            elif operator == "eq":
                mask = mask & (result[variable] == value)
            elif operator == "ne":
                mask = mask & (result[variable] != value)
            elif operator == "gt":
                mask = mask & (result[variable] > value)
            elif operator == "lt":
                mask = mask & (result[variable] < value)
            elif operator == "gte":
                mask = mask & (result[variable] >= value)
            elif operator == "lte":
                mask = mask & (result[variable] <= value)

        result = result[mask]

    return result


def preview_segment(df: pd.DataFrame, conditions: list[dict[str, Any]]) -> dict[str, Any]:
    """Preview segment: how many rows match, sample values."""
    filtered = resolve_segment_filter(df, conditions)

    return {
        "total_rows": len(df),
        "matching_rows": len(filtered),
        "match_percentage": round(len(filtered) / len(df) * 100, 1) if len(df) > 0 else 0,
        "sample_indices": filtered.index.tolist()[:10],
    }
