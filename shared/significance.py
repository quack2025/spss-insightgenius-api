"""Significance testing with proper Bonferroni correction.

This module centralizes ALL pairwise significance testing to ensure:
1. Bonferroni correction is applied consistently
2. Failures are logged (never silently swallowed)
3. Warnings are collected and returned to the user

Industry standard: Column proportion z-test with Bonferroni adjustment.
Bonferroni: alpha_adjusted = alpha / n_comparisons
Where n_comparisons = K*(K-1)/2 for K columns (all pairwise).
"""

import logging
import math
from typing import Any

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


def bonferroni_alpha(alpha: float, n_columns: int) -> float:
    """Compute Bonferroni-adjusted alpha for pairwise comparisons.

    For K columns, there are K*(K-1)/2 unique pairs.
    Adjusted alpha = raw_alpha / n_pairs.
    """
    if n_columns <= 1:
        return alpha
    n_pairs = n_columns * (n_columns - 1) / 2
    return alpha / n_pairs


def z_test_proportions(
    p1: float, n1: float, p2: float, n2: float,
    alpha: float, n_columns: int,
    apply_bonferroni: bool = True,
    variable: str = "", col_a: str = "", col_b: str = "",
    warnings_list: list | None = None,
) -> tuple[float, bool]:
    """Column proportion z-test with optional Bonferroni correction.

    Args:
        p1, n1: proportion and base for column A
        p2, n2: proportion and base for column B
        alpha: raw significance level (e.g., 0.05)
        n_columns: total number of banner columns (for Bonferroni)
        apply_bonferroni: whether to adjust alpha
        variable: variable name (for logging)
        col_a, col_b: column labels (for logging)
        warnings_list: optional list to append warnings to

    Returns:
        (p_value, is_significant)
    """
    if n1 <= 0 or n2 <= 0:
        return 1.0, False

    adjusted_alpha = bonferroni_alpha(alpha, n_columns) if apply_bonferroni else alpha

    try:
        p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
        if se <= 0:
            return 1.0, False
        z = (p1 - p2) / se
        p_val = 2 * stats.norm.sf(abs(z))
        is_sig = p_val < adjusted_alpha and p1 > p2
        return p_val, is_sig
    except (ZeroDivisionError, ValueError, FloatingPointError) as e:
        if warnings_list is not None:
            warnings_list.append(
                f"Sig test failed for {variable} ({col_a} vs {col_b}): {e}"
            )
        else:
            logger.warning("Sig test failed for %s (%s vs %s): %s", variable, col_a, col_b, e)
        return 1.0, False


def t_test_means(
    mean1: float, std1: float, n1: float,
    mean2: float, std2: float, n2: float,
    alpha: float, n_columns: int,
    apply_bonferroni: bool = True,
    variable: str = "", col_a: str = "", col_b: str = "",
    warnings_list: list | None = None,
) -> tuple[float, bool]:
    """Independent samples t-test with optional Bonferroni correction.

    Uses Welch's t-test (unequal variances).

    Returns:
        (p_value, is_significant) — significant if mean1 > mean2
    """
    if n1 <= 1 or n2 <= 1:
        return 1.0, False

    adjusted_alpha = bonferroni_alpha(alpha, n_columns) if apply_bonferroni else alpha

    try:
        se = math.sqrt((std1 ** 2 / n1) + (std2 ** 2 / n2))
        if se <= 0:
            return 1.0, False
        t_stat = (mean1 - mean2) / se

        # Welch-Satterthwaite degrees of freedom
        num = ((std1 ** 2 / n1) + (std2 ** 2 / n2)) ** 2
        den = ((std1 ** 2 / n1) ** 2 / (n1 - 1)) + ((std2 ** 2 / n2) ** 2 / (n2 - 1))
        if den <= 0:
            return 1.0, False
        df = num / den

        p_val = 2 * stats.t.sf(abs(t_stat), df)
        is_sig = p_val < adjusted_alpha and mean1 > mean2
        return p_val, is_sig
    except (ZeroDivisionError, ValueError, FloatingPointError) as e:
        if warnings_list is not None:
            warnings_list.append(
                f"T-test failed for {variable} ({col_a} vs {col_b}): {e}"
            )
        else:
            logger.warning("T-test failed for %s (%s vs %s): %s", variable, col_a, col_b, e)
        return 1.0, False
