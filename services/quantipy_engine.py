"""Core SPSS processing engine — stateless wrapper around QuantipyMRX + pandas.

Every function receives raw data and returns results. No instance state between requests.
All CPU-bound operations should be called via asyncio.to_thread() from routers.
"""

import logging
import math
import os
import string
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pyreadstat
from scipy import stats
from statsmodels.stats.proportion import proportions_ztest

logger = logging.getLogger(__name__)

# QuantipyMRX — graceful fallback
try:
    from quantipymrx import DataSet
    from quantipymrx.analysis.auto_detect import auto_detect as mrx_auto_detect
    from quantipymrx.analysis.crosstab import crosstab as mrx_crosstab
    from quantipymrx.analysis.significance import z_test_proportions as mrx_z_test, t_test_means as mrx_t_test
    from quantipymrx.analysis.mrx import calculate_nps as mrx_nps

    QUANTIPYMRX_AVAILABLE = True
    logger.info("QuantipyMRX loaded successfully")
except ImportError:
    QUANTIPYMRX_AVAILABLE = False
    DataSet = None  # type: ignore[assignment,misc]
    logger.warning("QuantipyMRX not available — pandas-only mode")


@dataclass
class SPSSData:
    """Container for loaded SPSS data: DataFrame + pyreadstat meta + optional MRX DataSet."""
    df: pd.DataFrame
    meta: Any  # pyreadstat metadata
    mrx_dataset: Any = None  # QuantipyMRX DataSet or None
    file_name: str = ""


def _sanitize_value(v: Any) -> Any:
    """Convert numpy types and NaN to JSON-safe Python types."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _get_user_missing(variable: str, meta: Any) -> set:
    """Get SPSS user-defined missing values for a variable."""
    if not meta:
        return set()
    missing_dict = getattr(meta, "missing_user_values", {})
    vals = missing_dict.get(variable, {})
    if isinstance(vals, dict):
        result = set()
        for key, val in vals.items():
            if val is not None:
                result.add(val)
        return result
    if isinstance(vals, (list, set)):
        return set(vals)
    return set()


def _strip_common_label_prefix(labels: list[str]) -> list[str]:
    """Strip the longest common prefix from SPSS MRS variable labels.

    Example:
        ["Q2b: Aided Importance: Fast onset", "Q2b: Aided Importance: Good score"]
        → ["Fast onset", "Good score"]
    """
    if len(labels) < 2:
        return labels
    prefix = labels[0]
    for lbl in labels[1:]:
        while not lbl.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return labels
    if len(prefix) < 5:
        return labels
    cleaned = []
    for lbl in labels:
        suffix = lbl[len(prefix):].lstrip(":;-–—/ \t")
        cleaned.append(suffix if len(suffix) >= 2 else lbl)
    return cleaned


def _frequency_via_mrx(data: "SPSSData", variable: str, weight: str | None) -> dict[str, Any] | None:
    """Delegate frequency to MRX and add mean/std/median."""
    from quantipymrx.analysis.frequency import frequency as mrx_frequency

    fr = mrx_frequency(data.mrx_dataset, variable, weight=weight)

    meta = data.meta
    col_labels = getattr(meta, "column_names_to_labels", {})
    value_labels_map = getattr(meta, "variable_value_labels", {}).get(variable, {})

    frequencies = []
    for val, row in fr.table.iterrows():
        if pd.isna(val):
            continue
        label = value_labels_map.get(val, str(val))
        frequencies.append({
            "value": _sanitize_value(val),
            "label": str(label),
            "count": int(row.get("count", 0)) if not weight else round(float(row.get("weighted_count", row.get("count", 0))), 1),
            "percentage": round(float(row.get("col_pct", row.get("percentage", 0))), 1),
        })

    frequencies.sort(key=lambda x: x["count"], reverse=True)

    result: dict[str, Any] = {
        "variable": variable,
        "label": col_labels.get(variable),
        "base": fr.base if hasattr(fr, "base") else int(fr.table["count"].sum()),
        "total_missing": getattr(fr, "missing", 0),
        "pct_missing": round(getattr(fr, "pct_missing", 0), 1),
        "frequencies": frequencies,
    }

    # NEW fields from MRX
    if hasattr(fr, "mean") and fr.mean is not None:
        result["mean"] = round(float(fr.mean), 2)
    if hasattr(fr, "std") and fr.std is not None:
        result["std"] = round(float(fr.std), 2)
    if hasattr(fr, "median") and fr.median is not None:
        result["median"] = round(float(fr.median), 2)
    result["is_weighted"] = weight is not None

    return result


def _crosstab_via_mrx(
    data: "SPSSData", row: str, col: str, weight: str | None, significance_level: float,
) -> dict[str, Any] | None:
    """Delegate crosstab to MRX native function and convert to API response shape."""
    alpha = 1 - significance_level
    sig_level_for_mrx = alpha  # MRX expects alpha (0.05), not confidence (0.95)

    ct = mrx_crosstab(
        data.mrx_dataset, x=row, y=col,
        weight=weight,
        sig_level=sig_level_for_mrx,
        test_significance=True,
        include_totals=True,
    )

    # Convert CrosstabResult to API response shape
    meta = data.meta
    row_value_labels = getattr(meta, "variable_value_labels", {}).get(row, {})
    col_value_labels = getattr(meta, "variable_value_labels", {}).get(col, {})

    col_values = sorted(ct.col_pct.columns.tolist())
    letters = list(string.ascii_uppercase[:len(col_values)])
    col_letter_map = {str(val): letters[i] for i, val in enumerate(col_values)}

    table = []
    for row_val in ct.col_pct.index:
        row_data: dict[str, Any] = {
            "row_value": _sanitize_value(row_val),
            "row_label": row_value_labels.get(row_val, str(row_val)),
        }
        for i, cv in enumerate(col_values):
            count = float(ct.counts.loc[row_val, cv]) if cv in ct.counts.columns else 0
            pct = float(ct.col_pct.loc[row_val, cv]) if cv in ct.col_pct.columns else 0

            # Get sig letters from MRX significance matrix
            sig_letters: list[str] = []
            if ct.significance is not None and cv in ct.significance.columns and row_val in ct.significance.index:
                sig_cell = ct.significance.loc[row_val, cv]
                if isinstance(sig_cell, str) and sig_cell:
                    # MRX returns sig letters directly as string like "AB"
                    sig_letters = list(sig_cell)

            row_data[str(cv)] = {
                "count": round(count, 1) if weight else int(count),
                "percentage": round(pct, 1),
                "column_letter": letters[i],
                "significance_letters": sorted(set(sig_letters)),
            }
        table.append(row_data)

    col_vl_map = {str(v): col_value_labels.get(v, str(v)) for v in col_values}
    total = int(ct.total_base) if ct.total_base else int(ct.counts.sum().sum())

    response: dict[str, Any] = {
        "row_variable": row,
        "col_variable": col,
        "total_responses": total,
        "table": table,
        "col_labels": col_letter_map,
        "col_value_labels": col_vl_map,
        "significance_level": significance_level,
        "significant_pairs": [],  # Not computed in MRX path (pairs are expensive and rarely used)
    }

    # Add chi-square (NEW — free from MRX)
    if ct.chi2 is not None:
        response["chi2"] = round(float(ct.chi2), 4)
        response["chi2_pvalue"] = round(float(ct.chi2_pvalue), 6) if ct.chi2_pvalue is not None else None
        response["chi2_warning"] = ct.chi2_warning

    return response


class QuantiProEngine:
    """Stateless SPSS processing engine."""

    @staticmethod
    def load_spss(file_bytes: bytes, file_name: str = "upload.sav") -> SPSSData:
        """Load .sav bytes into SPSSData (DataFrame + meta + optional MRX DataSet).

        This is a blocking/CPU-bound operation — call via asyncio.to_thread().
        """
        # Use mkstemp instead of NamedTemporaryFile to avoid Windows file locking
        fd, tmp_path = tempfile.mkstemp(suffix=".sav")
        try:
            os.write(fd, file_bytes)
            os.close(fd)

            # Load via pyreadstat (always reliable)
            df, meta = pyreadstat.read_sav(tmp_path)
            logger.info("Loaded SPSS: %d cases x %d variables", len(df), len(df.columns))

            # Load via QuantipyMRX (optional, for auto_detect + crosstab_with_sig)
            mrx_dataset = None
            if QUANTIPYMRX_AVAILABLE:
                try:
                    mrx_dataset = DataSet.from_spss(tmp_path, text_key="en-US")
                except Exception as e:
                    logger.warning("MRX DataSet load failed (pandas still available): %s", e)

            return SPSSData(df=df, meta=meta, mrx_dataset=mrx_dataset, file_name=file_name)
        finally:
            os.unlink(tmp_path)

    @staticmethod
    def load_spss_metadata_only(file_bytes: bytes) -> tuple[Any, str]:
        """Load only SPSS metadata (no data rows). Very fast.

        Returns (meta, tmp_path_for_mrx).
        """
        fd, tmp_path = tempfile.mkstemp(suffix=".sav")
        try:
            os.write(fd, file_bytes)
            os.close(fd)
            _, meta = pyreadstat.read_sav(tmp_path, metadataonly=True)
            return meta, tmp_path
        except Exception:
            os.unlink(tmp_path)
            raise

    @staticmethod
    def extract_metadata(data: SPSSData) -> dict[str, Any]:
        """Extract comprehensive metadata from loaded SPSS data."""
        df = data.df
        meta = data.meta

        col_labels = getattr(meta, "column_names_to_labels", {})
        value_labels = getattr(meta, "variable_value_labels", {})
        col_formats = getattr(meta, "original_variable_types", {})

        variables = []
        for col in df.columns:
            series = df[col]
            user_missing = _get_user_missing(col, meta)
            valid_mask = series.notna()
            if user_missing:
                valid_mask = valid_mask & ~series.isin(user_missing)

            # Determine type
            if pd.api.types.is_numeric_dtype(series):
                var_type = "numeric"
            elif pd.api.types.is_datetime64_any_dtype(series):
                var_type = "date"
            else:
                var_type = "string"

            # Value labels for this variable
            var_value_labels = value_labels.get(col, {})
            vl_dict = {str(k): str(v) for k, v in var_value_labels.items()} if var_value_labels else None

            variables.append({
                "name": col,
                "label": col_labels.get(col),
                "type": var_type,
                "measurement": None,  # SPSS measurement level not in pyreadstat
                "n_valid": int(valid_mask.sum()),
                "n_missing": int((~valid_mask).sum()),
                "value_labels": vl_dict,
                "detected_type": None,  # Filled by auto_detect
            })

        # Detect weight variables (heuristic: name contains 'weight' or 'wt' or 'pond')
        weight_candidates = [
            col for col in df.columns
            if any(w in col.lower() for w in ["weight", "wt_", "_wt", "pond", "ponder"])
        ]

        # Auto-detect via MRX
        auto_detect_result = None
        if data.mrx_dataset is not None:
            try:
                auto_detect_result = QuantiProEngine.auto_detect(data)
            except Exception as e:
                logger.warning("auto_detect failed: %s", e)

        return {
            "file_name": data.file_name,
            "n_cases": len(df),
            "n_variables": len(df.columns),
            "variables": variables,
            "detected_weights": weight_candidates,
            "auto_detect": auto_detect_result,
            "file_label": getattr(meta, "file_label", None),
        }

    @staticmethod
    def auto_detect(data: SPSSData, timeout: int = 10) -> dict[str, Any] | None:
        """Run QuantipyMRX auto_detect with timeout protection."""
        if data.mrx_dataset is None:
            return None

        def _run():
            spec = mrx_auto_detect(data.mrx_dataset)
            if spec is not None and hasattr(spec, "to_dict"):
                return spec.to_dict()
            return {}

        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                future = pool.submit(_run)
                return future.result(timeout=timeout)
            except FuturesTimeoutError:
                logger.warning("auto_detect timed out after %ds", timeout)
                return None
            except Exception as e:
                logger.warning("auto_detect failed: %s", e)
                return None

    @staticmethod
    def frequency(
        data: SPSSData,
        variable: str,
        weight: str | None = None,
    ) -> dict[str, Any]:
        """Frequency table for a single variable. Delegates to MRX when available."""
        df = data.df
        meta = data.meta

        if variable not in df.columns:
            raise ValueError(f"Variable '{variable}' not found in dataset")

        # Try MRX native frequency
        if data.mrx_dataset is not None:
            try:
                result = _frequency_via_mrx(data, variable, weight)
                if result is not None:
                    return result
            except Exception as e:
                logger.warning("MRX frequency failed for %s, falling back: %s", variable, e)

        user_missing = _get_user_missing(variable, meta)
        col_labels = getattr(meta, "column_names_to_labels", {})
        value_labels_map = getattr(meta, "variable_value_labels", {}).get(variable, {})

        # Weight series
        w = None
        if weight and weight in df.columns:
            w = df[weight]

        if w is not None:
            # Weighted frequency
            valid_mask = df[variable].notna()
            if user_missing:
                valid_mask = valid_mask & ~df[variable].isin(user_missing)
            total_weight = float(w[valid_mask].sum())

            frequencies = []
            weighted_missing = 0.0
            for value in df[variable].dropna().unique():
                if value in user_missing:
                    mask = df[variable] == value
                    weighted_missing += float(w[mask].sum())
                    continue
                mask = df[variable] == value
                wc = float(w[mask].sum())
                label = value_labels_map.get(value, str(value))
                frequencies.append({
                    "value": _sanitize_value(value),
                    "label": str(label),
                    "count": round(wc, 1),
                    "percentage": round((wc / total_weight * 100) if total_weight > 0 else 0, 1),
                })

            # Add NaN missing
            nan_mask = df[variable].isna()
            weighted_missing += float(w[nan_mask].sum())

            frequencies.sort(key=lambda x: x["count"], reverse=True)
            total_all_w = float(w.sum())

            return {
                "variable": variable,
                "label": col_labels.get(variable),
                "base": round(total_weight, 1),
                "total_missing": int(round(weighted_missing)),
                "pct_missing": round(weighted_missing / total_all_w * 100, 1) if total_all_w > 0 else 0.0,
                "frequencies": frequencies,
            }

        # Unweighted path
        valid_series = df[variable].dropna()
        if user_missing:
            valid_series = valid_series[~valid_series.isin(user_missing)]
        total = len(valid_series)
        total_all = len(df)

        value_counts = df[variable].value_counts(dropna=False)
        frequencies = []
        missing_count = 0

        for value, count in value_counts.items():
            is_missing = pd.isna(value) or value in user_missing
            if is_missing:
                missing_count += int(count)
                continue
            label = value_labels_map.get(value, str(value))
            pct = round((count / total * 100) if total > 0 else 0, 1)
            frequencies.append({
                "value": _sanitize_value(value),
                "label": str(label),
                "count": int(count),
                "percentage": pct,
            })

        frequencies.sort(key=lambda x: x["count"], reverse=True)

        return {
            "variable": variable,
            "label": col_labels.get(variable),
            "base": total,
            "total_missing": missing_count,
            "pct_missing": round(missing_count / total_all * 100, 1) if total_all > 0 else 0.0,
            "frequencies": frequencies,
        }

    @staticmethod
    def crosstab_with_significance(
        data: SPSSData,
        row: str,
        col: str,
        weight: str | None = None,
        significance_level: float = 0.95,
    ) -> dict[str, Any]:
        """Crosstab with column proportion significance testing (A/B/C letter notation).

        Uses proportions_ztest for unweighted, effective-n z-test for weighted.
        """
        df = data.df
        meta = data.meta

        if row not in df.columns:
            raise ValueError(f"Row variable '{row}' not found in dataset")
        if col not in df.columns:
            raise ValueError(f"Column variable '{col}' not found in dataset")

        # Try MRX native crosstab first
        if data.mrx_dataset is not None:
            try:
                result = _crosstab_via_mrx(data, row, col, weight, significance_level)
                if result is not None:
                    return result
            except Exception as e:
                logger.warning("MRX crosstab failed for %s x %s, falling back to pandas: %s", row, col, e)

        w = df[weight] if weight and weight in df.columns else None

        # Value labels
        row_value_labels = getattr(meta, "variable_value_labels", {}).get(row, {})
        col_value_labels = getattr(meta, "variable_value_labels", {}).get(col, {})
        col_labels_map = getattr(meta, "column_names_to_labels", {})

        alpha = 1 - significance_level

        if w is not None:
            # Weighted path
            valid = df[[row, col]].dropna()
            w_valid = w.loc[valid.index]
            weighted_ct = valid.assign(_w=w_valid).groupby([row, col])["_w"].sum().unstack(fill_value=0)

            if weighted_ct.empty:
                raise ValueError(f"No valid observations for {row} x {col}")

            col_values = sorted(weighted_ct.columns.tolist())
            letters = list(string.ascii_uppercase[:len(col_values)])
            col_letter_map = {str(val): letters[i] for i, val in enumerate(col_values)}
            w_col_totals = weighted_ct.sum(axis=0)

            # Effective n per column (Kish design effect)
            col_eff_n = {}
            for cv in col_values:
                col_mask = valid[col] == cv
                cw = w_valid[col_mask]
                sw = float(cw.sum())
                sw2 = float((cw ** 2).sum())
                col_eff_n[cv] = sw ** 2 / sw2 if sw2 > 0 else 0

            table = []
            significant_pairs = []

            for row_val in weighted_ct.index:
                row_data = {
                    "row_value": _sanitize_value(row_val),
                    "row_label": row_value_labels.get(row_val, str(row_val)),
                }
                for i, cv in enumerate(col_values):
                    wc = float(weighted_ct.loc[row_val, cv]) if cv in weighted_ct.columns else 0
                    ct = float(w_col_totals[cv])
                    pct = round((wc / ct * 100) if ct > 0 else 0, 1)

                    sig_letters = []
                    for j, ocv in enumerate(col_values):
                        if i == j:
                            continue
                        owc = float(weighted_ct.loc[row_val, ocv]) if ocv in weighted_ct.columns else 0
                        oct = float(w_col_totals[ocv])
                        try:
                            n_eff_i = col_eff_n[cv]
                            n_eff_j = col_eff_n[ocv]
                            p_i = wc / ct if ct > 0 else 0
                            p_j = owc / oct if oct > 0 else 0
                            p_pool = (wc + owc) / (ct + oct) if (ct + oct) > 0 else 0
                            se = np.sqrt(p_pool * (1 - p_pool) * (1 / n_eff_i + 1 / n_eff_j)) if n_eff_i > 0 and n_eff_j > 0 else 0
                            if se > 0:
                                z_stat = (p_i - p_j) / se
                                p_val = float(2 * stats.norm.sf(abs(z_stat)))
                            else:
                                p_val = 1.0
                            if p_val < alpha and p_i > p_j:
                                sig_letters.append(letters[j])
                                significant_pairs.append({
                                    "row_value": _sanitize_value(row_val),
                                    "col1": str(cv), "col1_letter": letters[i],
                                    "col2": str(ocv), "col2_letter": letters[j],
                                    "p_value": round(p_val, 4),
                                    "higher_column": letters[i],
                                })
                        except Exception:
                            pass

                    row_data[str(cv)] = {
                        "count": round(float(wc), 1),
                        "percentage": pct,
                        "column_letter": letters[i],
                        "significance_letters": sorted(set(sig_letters)),
                    }
                table.append(row_data)

            col_vl_map = {str(v): col_value_labels.get(v, str(v)) for v in col_values}
            return {
                "row_variable": row,
                "col_variable": col,
                "total_responses": int(round(float(w_col_totals.sum()))),
                "table": table,
                "col_labels": col_letter_map,
                "col_value_labels": col_vl_map,
                "significance_level": significance_level,
                "significant_pairs": significant_pairs,
            }

        # Unweighted path
        crosstab = pd.crosstab(df[row], df[col])
        if crosstab.empty:
            raise ValueError(f"No valid observations for {row} x {col}")

        col_values = sorted(crosstab.columns.tolist())
        letters = list(string.ascii_uppercase[:len(col_values)])
        col_letter_map = {str(val): letters[i] for i, val in enumerate(col_values)}
        col_totals = crosstab.sum(axis=0)

        table = []
        significant_pairs = []

        for row_val in crosstab.index:
            row_data = {
                "row_value": _sanitize_value(row_val),
                "row_label": row_value_labels.get(row_val, str(row_val)),
            }
            for i, cv in enumerate(col_values):
                count = int(crosstab.loc[row_val, cv])
                col_total = int(col_totals[cv])
                pct = round((count / col_total * 100) if col_total > 0 else 0, 1)

                sig_letters = []
                for j, ocv in enumerate(col_values):
                    if i == j:
                        continue
                    other_count = int(crosstab.loc[row_val, ocv])
                    other_total = int(col_totals[ocv])
                    try:
                        z_stat, p_val = proportions_ztest(
                            [count, other_count],
                            [col_total, other_total],
                            alternative="two-sided",
                        )
                        this_pct = count / col_total if col_total > 0 else 0
                        other_pct = other_count / other_total if other_total > 0 else 0
                        if p_val < alpha and this_pct > other_pct:
                            sig_letters.append(letters[j])
                            significant_pairs.append({
                                "row_value": _sanitize_value(row_val),
                                "col1": str(cv), "col1_letter": letters[i],
                                "col2": str(ocv), "col2_letter": letters[j],
                                "p_value": round(float(p_val), 4),
                                "higher_column": letters[i],
                            })
                    except Exception:
                        pass

                row_data[str(cv)] = {
                    "count": count,
                    "percentage": pct,
                    "column_letter": letters[i],
                    "significance_letters": sorted(set(sig_letters)),
                }
            table.append(row_data)

        col_vl_map = {str(v): col_value_labels.get(v, str(v)) for v in col_values}
        return {
            "row_variable": row,
            "col_variable": col,
            "total_responses": int(crosstab.sum().sum()),
            "table": table,
            "col_labels": col_letter_map,
            "col_value_labels": col_vl_map,
            "significance_level": significance_level,
            "significant_pairs": significant_pairs,
        }

    @staticmethod
    def nps(data: SPSSData, variable: str, weight: str | None = None) -> dict[str, Any]:
        """Net Promoter Score: 9-10=promoter, 7-8=passive, 0-6=detractor."""
        df = data.df
        if variable not in df.columns:
            raise ValueError(f"Variable '{variable}' not found in dataset")

        col_labels = getattr(data.meta, "column_names_to_labels", {})

        # Try MRX native NPS
        if data.mrx_dataset is not None:
            try:
                series = df[variable].dropna()
                nps_result = mrx_nps(series, scale="0-10")
                return {
                    "variable": variable,
                    "label": col_labels.get(variable),
                    "nps_score": round(float(nps_result.nps), 1),
                    "base": nps_result.base,
                    "promoters": {"count": nps_result.promoters_count, "percentage": round(nps_result.promoters_pct, 1)},
                    "passives": {"count": nps_result.passives_count, "percentage": round(nps_result.passives_pct, 1)},
                    "detractors": {"count": nps_result.detractors_count, "percentage": round(nps_result.detractors_pct, 1)},
                }
            except Exception as e:
                logger.warning("MRX NPS failed for %s, falling back: %s", variable, e)

        series = df[variable].dropna()
        base = len(series)
        if base == 0:
            raise ValueError(f"No valid data for variable '{variable}'")

        promoters = int((series >= 9).sum())
        passives = int(((series >= 7) & (series < 9)).sum())
        detractors = int((series < 7).sum())

        prom_pct = round(promoters / base * 100, 1)
        det_pct = round(detractors / base * 100, 1)
        score = round(prom_pct - det_pct, 1)

        return {
            "variable": variable,
            "label": col_labels.get(variable),
            "nps_score": score,
            "base": base,
            "promoters": {"count": promoters, "percentage": prom_pct},
            "passives": {"count": passives, "percentage": round(passives / base * 100, 1)},
            "detractors": {"count": detractors, "percentage": det_pct},
        }

    @staticmethod
    def top_bottom_box(
        data: SPSSData,
        variable: str,
        top_values: list[Any] | None = None,
        bottom_values: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Top Box / Bottom Box scores with auto-detect of scale endpoints."""
        df = data.df
        if variable not in df.columns:
            raise ValueError(f"Variable '{variable}' not found in dataset")

        series = df[variable].dropna()
        col_labels = getattr(data.meta, "column_names_to_labels", {})
        user_missing = _get_user_missing(variable, data.meta)
        if user_missing:
            series = series[~series.isin(user_missing)]
        base = len(series)
        if base == 0:
            raise ValueError(f"No valid data for variable '{variable}'")

        if top_values is None:
            max_val = series.max()
            top_values = [max_val, max_val - 1] if max_val > 2 else [max_val]
        if bottom_values is None:
            min_val = series.min()
            bottom_values = [min_val, min_val + 1] if min_val < series.max() - 1 else [min_val]

        top_count = int(series.isin(top_values).sum())
        bot_count = int(series.isin(bottom_values).sum())

        return {
            "variable": variable,
            "label": col_labels.get(variable),
            "base": base,
            "top_box": {
                "values": [_sanitize_value(v) for v in top_values],
                "count": top_count,
                "percentage": round(top_count / base * 100, 1),
            },
            "bottom_box": {
                "values": [_sanitize_value(v) for v in bottom_values],
                "count": bot_count,
                "percentage": round(bot_count / base * 100, 1),
            },
        }

    @staticmethod
    def nets(
        data: SPSSData,
        variable: str,
        net_definitions: dict[str, list[Any]],
    ) -> dict[str, Any]:
        """Net scores — grouped response counts by user-defined nets."""
        df = data.df
        if variable not in df.columns:
            raise ValueError(f"Variable '{variable}' not found in dataset")

        series = df[variable].dropna()
        col_labels = getattr(data.meta, "column_names_to_labels", {})
        user_missing = _get_user_missing(variable, data.meta)
        if user_missing:
            series = series[~series.isin(user_missing)]
        base = len(series)

        results = {}
        for name, values in net_definitions.items():
            count = int(series.isin(values).sum())
            results[name] = {
                "values": [_sanitize_value(v) for v in values],
                "count": count,
                "percentage": round(count / base * 100, 1) if base > 0 else 0,
            }

        return {
            "variable": variable,
            "label": col_labels.get(variable),
            "base": base,
            "nets": results,
        }
