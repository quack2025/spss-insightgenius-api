"""Data Preparation Service — applies rules to DataFrames before analysis.

Rule types and their effects:
- cleaning: Drop/filter rows by condition
- weight: RIM weighting via IPF (delegates to rim_weighter)
- net: Create binary column from code groups (e.g., Top 2 Box)
- recode: Map codes to new values
- computed: Create new variable from conditions

Rules are applied in order_index sequence: cleaning → computed → nets/recodes → weights.
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MAX_RULES_PER_PROJECT = 50


def apply_rules(df: pd.DataFrame, rules: list[dict[str, Any]]) -> pd.DataFrame:
    """Apply a list of data prep rules to a DataFrame.

    Args:
        df: Raw DataFrame from SPSS
        rules: List of rule dicts with keys: rule_type, config, is_active

    Returns:
        Modified DataFrame (copy — original is not mutated)
    """
    if not rules:
        return df

    result = df.copy()
    active_rules = [r for r in rules if r.get("is_active", True)]

    # Sort by order_index
    active_rules.sort(key=lambda r: r.get("order_index", 0))

    for rule in active_rules:
        rule_type = rule.get("rule_type", "")
        config = rule.get("config", {})

        try:
            if rule_type == "cleaning":
                result = _apply_cleaning(result, config)
            elif rule_type == "weight":
                result = _apply_weight(result, config)
            elif rule_type == "net":
                result = _apply_net(result, config)
            elif rule_type == "recode":
                result = _apply_recode(result, config)
            elif rule_type == "computed":
                result = _apply_computed(result, config)
        except Exception as e:
            logger.warning("Rule %s failed: %s", rule.get("name", rule_type), e)

    return result


def preview_rule(
    df: pd.DataFrame,
    rule_type: str,
    config: dict[str, Any],
    existing_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Preview the impact of a rule without persisting it.

    Applies existing rules first (cumulative), then the new rule.
    Returns before/after counts.
    """
    # Apply existing rules first (cumulative preview)
    if existing_rules:
        df = apply_rules(df, existing_rules)

    before_rows = len(df)
    before_cols = len(df.columns)

    modified = apply_rules(df, [{"rule_type": rule_type, "config": config, "is_active": True}])

    after_rows = len(modified)
    after_cols = len(modified.columns)

    return {
        "before": {"rows": before_rows, "columns": before_cols},
        "after": {"rows": after_rows, "columns": after_cols},
        "rows_removed": before_rows - after_rows,
        "columns_added": after_cols - before_cols,
    }


# ─── Rule Implementations ────────────────────────────────────────────────


def _apply_cleaning(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Drop or filter rows by condition."""
    variable = config.get("variable", "")
    operator = config.get("operator", "equals")
    value = config.get("value")
    action = config.get("action", "drop")  # "drop" or "filter" (keep matching)

    if variable not in df.columns:
        return df

    mask = _build_match_mask(df, variable, operator, value)

    if action == "filter":
        return df[mask].reset_index(drop=True)
    else:  # drop
        return df[~mask].reset_index(drop=True)


def _build_match_mask(df: pd.DataFrame, variable: str, operator: str, value: Any) -> pd.Series:
    """Build boolean mask where True = row matches the condition."""
    series = df[variable]

    if operator == "equals":
        return series == value
    elif operator == "not_equals":
        return series != value
    elif operator == "less_than":
        return series < value
    elif operator == "greater_than":
        return series > value
    elif operator == "in":
        return series.isin(value if isinstance(value, list) else [value])
    elif operator == "not_in":
        return ~series.isin(value if isinstance(value, list) else [value])
    elif operator == "is_null":
        return series.isna()
    elif operator == "is_not_null":
        return series.notna()
    else:
        return pd.Series(False, index=df.index)


def _apply_weight(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Create _weight column via RIM weighting (delegates to rim_weighter)."""
    targets = config.get("targets", {})
    weight_name = config.get("weight_name", "_weight")

    if not targets:
        return df

    try:
        from services.rim_weighter import compute_rim_weights
        weights = compute_rim_weights(df, targets)
        df[weight_name] = weights
    except Exception as e:
        logger.warning("RIM weighting failed: %s", e)

    return df


def _apply_net(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Create a binary net column (1 if value in codes, else 0)."""
    variable = config.get("variable", "")
    net_name = config.get("net_name", f"{variable}_net")
    codes = config.get("codes", [])

    if variable not in df.columns or not codes:
        return df

    df[net_name] = df[variable].isin(codes).astype(int)
    return df


def _apply_recode(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Map values to new codes."""
    variable = config.get("variable", "")
    mappings = config.get("mappings", [])
    target = config.get("target_variable", variable)

    if variable not in df.columns or not mappings:
        return df

    mapping_dict = {}
    for m in mappings:
        old_values = m.get("old_values", [])
        new_value = m.get("new_value")
        for ov in old_values:
            mapping_dict[ov] = new_value

    df[target] = df[variable].map(mapping_dict).fillna(df[variable])
    return df


def _apply_computed(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Create a new variable from conditions."""
    name = config.get("name", "computed_var")
    conditions = config.get("conditions", [])
    combine = config.get("combine", "or")  # "or" or "and"
    default_value = config.get("default_value", 0)

    if not conditions:
        return df

    masks = []
    for cond in conditions:
        variable = cond.get("variable", "")
        operator = cond.get("operator", "equals")
        value = cond.get("value")
        if variable in df.columns:
            masks.append(_build_match_mask(df, variable, operator, value))

    if not masks:
        df[name] = default_value
        return df

    if combine == "and":
        combined = masks[0]
        for m in masks[1:]:
            combined = combined & m
    else:  # or
        combined = masks[0]
        for m in masks[1:]:
            combined = combined | m

    df[name] = np.where(combined, 1, default_value)
    return df
