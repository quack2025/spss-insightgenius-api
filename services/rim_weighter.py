"""RIM (Raking / Iterative Proportional Fitting) weighting engine.

Computes weights that adjust a sample to match target population distributions
on one or more demographic variables simultaneously.

Algorithm: Standard iterative proportional fitting.
Reference: Talk2Data's StatisticsService.rim_weight() (Sprint 24).
"""

from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class WeightTarget:
    """Target distribution for one variable."""
    variable: str
    targets: dict[str, float]  # {value_as_str: target_percentage}


@dataclass
class WeightResult:
    """Result of RIM weight computation."""
    converged: bool
    iterations: int
    effective_n: float
    efficiency: float  # effective_n / actual_n * 100
    weight_stats: dict  # min, max, mean, std, extreme_count
    weighted_distributions: list[dict]  # before/after comparison per variable
    weight_column: str  # name of weight column added to df


def compute_rim_weight(
    df: pd.DataFrame,
    targets: list[WeightTarget],
    weight_name: str = "rim_weight",
    max_iterations: int = 50,
    convergence: float = 0.001,
    min_weight: float = 0.1,
    max_weight: float = 5.0,
) -> tuple[pd.Series, WeightResult]:
    """Compute RIM weight via iterative proportional fitting.

    Args:
        df: DataFrame with the survey data.
        targets: List of WeightTarget (variable + target percentages that sum to 100).
        weight_name: Name for the weight column.
        max_iterations: Max iterations before stopping.
        convergence: Stop when max deviation between target and weighted % < this.
        min_weight: Minimum allowed weight (prevents extreme down-weighting).
        max_weight: Maximum allowed weight (prevents extreme up-weighting).

    Returns:
        Tuple of (weight_series, WeightResult).

    Raises:
        ValueError: If variable not found, targets don't sum to ~100%, or
                    a target value has zero cases in the data.
    """
    n = len(df)
    if n == 0:
        raise ValueError("DataFrame is empty.")

    # Validate targets
    for t in targets:
        if t.variable not in df.columns:
            raise ValueError(f"Variable '{t.variable}' not found in data.")
        total = sum(t.targets.values())
        if abs(total - 100.0) > 1.0:
            raise ValueError(
                f"Targets for '{t.variable}' sum to {total:.1f}%, must be ~100%."
            )

    # Convert target percentages to proportions
    target_props: dict[str, dict[float, float]] = {}
    for t in targets:
        target_props[t.variable] = {}
        for val_str, pct in t.targets.items():
            val = float(val_str)
            mask = df[t.variable] == val
            if mask.sum() == 0:
                raise ValueError(
                    f"Value {val_str} of '{t.variable}' has 0 cases — cannot weight."
                )
            target_props[t.variable][val] = pct / 100.0

    # Initialize weights to 1
    weights = np.ones(n, dtype=float)

    # Iterative proportional fitting
    converged = False
    iteration = 0

    for iteration in range(max_iterations):
        max_diff = 0.0

        for var, var_targets in target_props.items():
            col = df[var].values
            for value, target_prop in var_targets.items():
                mask = col == value
                if mask.sum() == 0:
                    continue

                current_sum = weights[mask].sum()
                total_sum = weights.sum()
                if total_sum == 0 or current_sum == 0:
                    continue

                current_prop = current_sum / total_sum
                adjustment = target_prop / current_prop
                weights[mask] *= adjustment

                max_diff = max(max_diff, abs(target_prop - current_prop))

        # Cap extreme weights, normalize, re-cap (normalization can push past cap)
        weights = np.clip(weights, min_weight, max_weight)
        w_sum = weights.sum()
        if w_sum > 0:
            weights *= n / w_sum
        weights = np.clip(weights, min_weight, max_weight)

        # Check convergence
        if max_diff < convergence:
            converged = True
            break

    # Compute stats
    effective_n = (weights.sum() ** 2) / (weights ** 2).sum()
    efficiency = (effective_n / n) * 100

    extreme_count = int(
        ((weights < min_weight * 1.01) | (weights > max_weight * 0.99)).sum()
    )

    # Build before/after distributions
    weighted_distributions = []
    for t in targets:
        dist = {"variable": t.variable, "before": [], "after": []}
        col = df[t.variable]
        for val_str, target_pct in t.targets.items():
            val = float(val_str)
            mask = col == val
            count = int(mask.sum())
            before_pct = round((count / n) * 100, 1) if n > 0 else 0
            after_pct = round(
                (weights[mask.values].sum() / weights.sum()) * 100, 1
            ) if weights.sum() > 0 else 0

            # Get label from value_labels if available
            dist["before"].append({
                "value": val_str,
                "count": count,
                "pct": before_pct,
                "target_pct": round(target_pct, 1),
            })
            dist["after"].append({
                "value": val_str,
                "pct": after_pct,
                "target_pct": round(target_pct, 1),
            })
        weighted_distributions.append(dist)

    result = WeightResult(
        converged=converged,
        iterations=iteration + 1,
        effective_n=round(effective_n, 1),
        efficiency=round(efficiency, 1),
        weight_stats={
            "min": round(float(weights.min()), 4),
            "max": round(float(weights.max()), 4),
            "mean": round(float(weights.mean()), 4),
            "std": round(float(weights.std()), 4),
            "extreme_count": extreme_count,
        },
        weighted_distributions=weighted_distributions,
        weight_column=weight_name,
    )

    return pd.Series(weights, index=df.index, name=weight_name), result
