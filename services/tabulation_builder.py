"""Tabulation Excel builder — professional market research crosstab tables.

Generates an .xlsx workbook where each sheet is one stub variable crossed by
one or more banners, with significance letters, nets, means, and proper formatting.

Output mirrors what WinCross / PSPP / Quantum produce.

Tier 1 features:
- T1-1: Means row with T-test significance letters
- T1-2: Multiple banners side-by-side with grouped headers
- T1-3: MRS groups as crosstab rows
- T1-4: Dual bases (weighted + unweighted)
"""

import io
import logging
import math
import string
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from scipy import stats

logger = logging.getLogger(__name__)

# ── Styling ──────────────────────────────────────────────────────────────────

TITLE_FONT = Font(bold=True, size=12, color="1F2937")
HEADER_FONT = Font(bold=True, size=10, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
BANNER_GROUP_FILL = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
LETTER_HEADER_FILL = PatternFill(start_color="1D4ED8", end_color="1D4ED8", fill_type="solid")
TOTAL_FILL = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")
NET_FILL = PatternFill(start_color="F0FDF4", end_color="F0FDF4", fill_type="solid")
MEAN_FILL = PatternFill(start_color="FFF7ED", end_color="FFF7ED", fill_type="solid")
SIG_FONT = Font(bold=True, size=9, color="DC2626")
BASE_FONT = Font(bold=True, size=10, color="6B7280")
LABEL_FONT = Font(size=10, color="1F2937")
PCT_FONT = Font(size=10, color="374151")
COUNT_FONT = Font(size=9, color="9CA3AF")
MEAN_FONT = Font(bold=True, size=10, color="9A3412")
MEAN_SIG_FONT = Font(bold=True, size=9, color="DC2626")
THIN_BORDER = Border(bottom=Side(style="thin", color="E5E7EB"))
HEADER_BORDER = Border(bottom=Side(style="medium", color="1D4ED8"))
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")


@dataclass
class TabulateSpec:
    """Specification for a full tabulation run."""
    banner: str = ""  # Single banner (backwards compat)
    banners: list[str] | None = None  # Multiple banners (T1-2)
    stubs: list[str] = field(default_factory=lambda: ["_all_"])
    weight: str | None = None
    significance_level: float = 0.95
    nets: dict[str, dict[str, list[Any]]] | None = None
    mrs_groups: dict[str, list[str]] | None = None  # T1-3: {"Q5_awareness": ["Q5_1","Q5_2",...]}
    include_means: bool = False  # T1-1
    show_counts: bool = True
    show_percentages: bool = True
    title: str = ""

    @property
    def resolved_banners(self) -> list[str]:
        """Return list of banners (supports single or multi)."""
        if self.banners:
            return self.banners
        if self.banner:
            return [self.banner]
        return []


@dataclass
class BannerColumn:
    """A single column in the output table (one value of one banner variable)."""
    banner_var: str
    banner_label: str
    value: str  # The column value (e.g., "1.0")
    value_label: str  # The display label (e.g., "Male")
    letter: str  # The assigned letter (A, B, C, ...)
    banner_index: int  # Which banner group this belongs to


@dataclass
class SheetResult:
    """Result for one stub variable."""
    variable: str
    label: str | None
    status: str
    error: str | None = None
    crosstab_data: dict[str, Any] | None = None
    is_mrs: bool = False
    mrs_members: list[str] | None = None


@dataclass
class TabulationResult:
    """Full tabulation result."""
    banners: list[str]
    banner_labels: list[str]
    total_stubs: int
    successful: int
    failed: int
    sheets: list[SheetResult] = field(default_factory=list)
    excel_bytes: bytes = b""
    banner_columns: list[BannerColumn] = field(default_factory=list)


def build_tabulation(engine_cls: Any, data: Any, spec: TabulateSpec) -> TabulationResult:
    """Run all crosstabs and build the Excel workbook. CPU-bound — call via asyncio.to_thread()."""
    from services.quantipy_engine import QuantiProEngine

    df = data.df
    meta = data.meta
    col_labels = getattr(meta, "column_names_to_labels", {})
    banners = spec.resolved_banners

    # ── Build banner columns with continuous letter assignment ──
    banner_columns: list[BannerColumn] = []
    letter_idx = 0
    all_letters = list(string.ascii_uppercase) + [a + b for a in string.ascii_uppercase for b in string.ascii_uppercase]

    for b_idx, banner_var in enumerate(banners):
        if banner_var not in df.columns:
            continue
        vl = getattr(meta, "variable_value_labels", {}).get(banner_var, {})
        # Get sorted unique values
        col_values = sorted(df[banner_var].dropna().unique())
        for cv in col_values:
            banner_columns.append(BannerColumn(
                banner_var=banner_var,
                banner_label=col_labels.get(banner_var, banner_var),
                value=str(cv),
                value_label=vl.get(cv, str(cv)),
                letter=all_letters[letter_idx],
                banner_index=b_idx,
            ))
            letter_idx += 1

    # ── Resolve stubs ──
    if spec.stubs == ["_all_"] or not spec.stubs:
        value_labels = getattr(meta, "variable_value_labels", {})
        banner_set = set(banners)
        stubs = [
            col for col in df.columns
            if col not in banner_set and col in value_labels and len(value_labels.get(col, {})) >= 2
        ]
        if not stubs:
            stubs = [col for col in df.columns if col not in banner_set and df[col].dtype.kind in ("i", "f")]
    else:
        stubs = spec.stubs

    result = TabulationResult(
        banners=banners,
        banner_labels=[col_labels.get(b, b) for b in banners],
        total_stubs=len(stubs) + len(spec.mrs_groups or {}),
        successful=0,
        failed=0,
        banner_columns=banner_columns,
    )

    # ── Run crosstabs for each stub × each banner ──
    for stub in stubs:
        try:
            # Run crosstab against FIRST banner (primary), store all banner results
            all_banner_results = {}
            for banner_var in banners:
                ct = QuantiProEngine.crosstab_with_significance(
                    data, row=stub, col=banner_var,
                    weight=spec.weight,
                    significance_level=spec.significance_level,
                )
                all_banner_results[banner_var] = ct

            sheet = SheetResult(
                variable=stub,
                label=col_labels.get(stub, stub),
                status="success",
                crosstab_data=all_banner_results,
            )
            result.successful += 1
        except Exception as e:
            sheet = SheetResult(variable=stub, label=col_labels.get(stub, stub), status="error", error=str(e))
            result.failed += 1
        result.sheets.append(sheet)

    # ── MRS groups (T1-3) ──
    for group_name, members in (spec.mrs_groups or {}).items():
        try:
            all_banner_results = {}
            for banner_var in banners:
                ct = _mrs_crosstab(data, members, banner_var, spec.weight, spec.significance_level)
                all_banner_results[banner_var] = ct
            group_label = col_labels.get(group_name, group_name)
            sheet = SheetResult(
                variable=group_name, label=group_label, status="success",
                crosstab_data=all_banner_results, is_mrs=True, mrs_members=members,
            )
            result.successful += 1
        except Exception as e:
            sheet = SheetResult(variable=group_name, label=str(group_name), status="error", error=str(e), is_mrs=True)
            result.failed += 1
        result.sheets.append(sheet)

    result.excel_bytes = _build_excel(result, spec, data)
    return result


def _mrs_crosstab(
    data: Any, members: list[str], col: str, weight: str | None, sig_level: float,
) -> dict[str, Any]:
    """Crosstab for a Multiple Response Set — each member is a row, base = total respondents."""
    df = data.df
    meta = data.meta
    col_labels = getattr(meta, "column_names_to_labels", {})
    col_vl = getattr(meta, "variable_value_labels", {}).get(col, {})

    valid = df[[col] + [m for m in members if m in df.columns]].dropna(subset=[col])
    w = valid[weight] if weight and weight in df.columns else None

    col_values = sorted(valid[col].dropna().unique())
    letters = list(string.ascii_uppercase[:len(col_values)])
    col_letter_map = {str(v): letters[i] for i, v in enumerate(col_values)}
    alpha = 1 - sig_level

    table = []
    for member in members:
        if member not in df.columns:
            continue
        member_label = col_labels.get(member, member)
        row_data = {"row_value": member, "row_label": member_label}

        for i, cv in enumerate(col_values):
            mask = valid[col] == cv
            subset = valid.loc[mask]
            # Count respondents who selected this option (value == 1 or value > 0)
            selected = (subset[member].fillna(0) > 0)
            if w is not None:
                w_sub = w.loc[subset.index]
                count = float((selected * w_sub).sum())
                base = float(w_sub.sum())
            else:
                count = int(selected.sum())
                base = len(subset)
            pct = round(count / base * 100, 1) if base > 0 else 0

            # Sig testing vs other columns
            sig_letters = []
            for j, ocv in enumerate(col_values):
                if i == j:
                    continue
                o_mask = valid[col] == ocv
                o_subset = valid.loc[o_mask]
                o_selected = (o_subset[member].fillna(0) > 0)
                if w is not None:
                    o_w = w.loc[o_subset.index]
                    o_count = float((o_selected * o_w).sum())
                    o_base = float(o_w.sum())
                else:
                    o_count = int(o_selected.sum())
                    o_base = len(o_subset)
                try:
                    p1 = count / base if base > 0 else 0
                    p2 = o_count / o_base if o_base > 0 else 0
                    p_pool = (count + o_count) / (base + o_base) if (base + o_base) > 0 else 0
                    se = np.sqrt(p_pool * (1 - p_pool) * (1 / max(base, 1) + 1 / max(o_base, 1)))
                    if se > 0:
                        z = (p1 - p2) / se
                        p_val = 2 * stats.norm.sf(abs(z))
                        if p_val < alpha and p1 > p2:
                            sig_letters.append(letters[j])
                except Exception:
                    pass

            row_data[str(cv)] = {
                "count": count, "percentage": pct,
                "column_letter": letters[i],
                "significance_letters": sorted(set(sig_letters)),
            }
        table.append(row_data)

    return {
        "row_variable": "MRS",
        "col_variable": col,
        "total_responses": len(valid),
        "table": table,
        "col_labels": col_letter_map,
        "col_value_labels": {str(v): col_vl.get(v, str(v)) for v in col_values},
        "significance_level": sig_level,
        "significant_pairs": [],
    }


# ── Means computation with T-test (T1-1) ──

def _compute_means_by_column(
    df: pd.DataFrame, stub: str, banner_var: str, col_values: list, weight: str | None, alpha: float,
) -> dict[str, Any]:
    """Compute mean per banner column with independent T-test significance letters."""
    results = {}
    series = df[stub]
    if not pd.api.types.is_numeric_dtype(series):
        return {}

    w = df[weight] if weight and weight in df.columns else None
    letters = list(string.ascii_uppercase[:len(col_values)])

    col_stats = {}
    for i, cv in enumerate(col_values):
        mask = (df[banner_var] == cv) & series.notna()
        vals = series[mask]
        if len(vals) < 2:
            col_stats[str(cv)] = {"mean": None, "std": None, "n": len(vals), "letter": letters[i], "values": vals}
            continue
        if w is not None:
            wv = w[mask]
            wmean = float(np.average(vals, weights=wv))
            # Weighted std dev
            wvar = float(np.average((vals - wmean) ** 2, weights=wv))
            wstd = float(np.sqrt(wvar))
            col_stats[str(cv)] = {"mean": wmean, "std": wstd, "n": len(vals), "letter": letters[i], "values": vals, "weights": wv}
        else:
            col_stats[str(cv)] = {"mean": float(vals.mean()), "std": float(vals.std()), "n": len(vals), "letter": letters[i], "values": vals}

    # T-test between each pair
    for cv_str, st in col_stats.items():
        if st["mean"] is None:
            results[cv_str] = {"mean": None, "std": None, "n": st["n"], "sig_letters": []}
            continue
        sig_letters = []
        for ocv_str, ost in col_stats.items():
            if cv_str == ocv_str or ost["mean"] is None:
                continue
            try:
                t_stat, p_val = stats.ttest_ind(st["values"], ost["values"], equal_var=False)
                if p_val < alpha and st["mean"] > ost["mean"]:
                    sig_letters.append(ost["letter"])
            except Exception:
                pass
        results[cv_str] = {
            "mean": round(st["mean"], 2),
            "std": round(st["std"], 2),
            "n": st["n"],
            "sig_letters": sorted(set(sig_letters)),
        }
    return results


# ── Excel builder ──

def _build_excel(result: TabulationResult, spec: TabulateSpec, data: Any) -> bytes:
    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = "Summary"
    _write_summary_sheet(ws_summary, result, spec, data)

    for sheet_result in result.sheets:
        if sheet_result.status != "success" or not sheet_result.crosstab_data:
            continue
        sheet_name = sheet_result.variable[:31]
        existing = [ws.title for ws in wb.worksheets]
        if sheet_name in existing:
            sheet_name = sheet_name[:28] + "_" + str(existing.count(sheet_name))
        ws = wb.create_sheet(title=sheet_name)
        _write_crosstab_sheet(ws, sheet_result, spec, data, result.banner_columns)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _write_summary_sheet(ws, result: TabulationResult, spec: TabulateSpec, data: Any):
    meta = data.meta
    col_labels = getattr(meta, "column_names_to_labels", {})

    title = spec.title or "Tabulation Report"
    ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=16, color="1F2937")
    ws.merge_cells("A1:F1")

    r = 3
    banners_str = " + ".join(f"{b} ({col_labels.get(b, '')})" for b in result.banners)
    info = [
        ("File", data.file_name),
        ("Cases", len(data.df)),
        ("Banners", banners_str),
        ("Weight", spec.weight or "(none)"),
        ("Significance Level", f"{spec.significance_level:.0%}"),
        ("Means with T-test", "Yes" if spec.include_means else "No"),
        ("Total Stubs", result.total_stubs),
        ("Successful", result.successful),
        ("Failed", result.failed),
    ]
    for label, value in info:
        ws.cell(row=r, column=1, value=label).font = Font(bold=True, size=10)
        ws.cell(row=r, column=2, value=str(value)).font = Font(size=10)
        r += 1

    # Column legend
    r += 1
    ws.cell(row=r, column=1, value="Column Legend").font = Font(bold=True, size=11)
    r += 1
    headers = ["Letter", "Banner", "Value", "Label"]
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=r, column=c, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
    r += 1
    for bc in result.banner_columns:
        ws.cell(row=r, column=1, value=bc.letter).font = Font(bold=True, size=10)
        ws.cell(row=r, column=1).alignment = CENTER
        ws.cell(row=r, column=2, value=bc.banner_label)
        ws.cell(row=r, column=3, value=bc.value)
        ws.cell(row=r, column=4, value=bc.value_label)
        r += 1

    # Stub index
    r += 1
    ws.cell(row=r, column=1, value="Stub Index").font = Font(bold=True, size=11)
    r += 1
    idx_headers = ["#", "Variable", "Label", "Type", "Status"]
    for c, h in enumerate(idx_headers, 1):
        cell = ws.cell(row=r, column=c, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
    r += 1
    for i, sheet in enumerate(result.sheets, 1):
        ws.cell(row=r, column=1, value=i)
        ws.cell(row=r, column=2, value=sheet.variable)
        ws.cell(row=r, column=3, value=sheet.label or "")
        ws.cell(row=r, column=4, value="MRS" if sheet.is_mrs else "Standard")
        ws.cell(row=r, column=5, value=sheet.status)
        if sheet.status == "error":
            ws.cell(row=r, column=5).font = Font(color="DC2626")
        r += 1

    for col_letter in ["A", "B", "C", "D", "E", "F"]:
        ws.column_dimensions[col_letter].width = [18, 25, 12, 45, 12, 20]["ABCDEF".index(col_letter)]


def _write_crosstab_sheet(ws, sheet_result: SheetResult, spec: TabulateSpec, data: Any, banner_columns: list[BannerColumn]):
    """Write one crosstab table with multiple banners side-by-side."""
    all_ct = sheet_result.crosstab_data  # dict[banner_var -> crosstab_result]
    if not all_ct:
        return

    banners = spec.resolved_banners
    n_banner_cols = len(banner_columns)
    total_col = 2 + n_banner_cols  # Last column = Total

    # Row 1: Title
    title = f"{sheet_result.variable}"
    if sheet_result.label:
        title += f": {sheet_result.label}"
    if sheet_result.is_mrs:
        title += " (Multiple Response)"
    ws.cell(row=1, column=1, value=title).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_col)

    # Row 2: Sig note
    sig_note = f"Significance: {spec.significance_level:.0%} confidence"
    if spec.weight:
        sig_note += f" | Weighted by: {spec.weight}"
    if len(banners) > 1:
        sig_note += f" | Sig testing within each banner group"
    ws.cell(row=2, column=1, value=sig_note).font = Font(italic=True, size=9, color="6B7280")

    # Row 3: Banner group headers (merged cells per banner)
    if len(banners) > 1:
        col_idx = 2
        for b_idx, banner_var in enumerate(banners):
            group_cols = [bc for bc in banner_columns if bc.banner_index == b_idx]
            if group_cols:
                cell = ws.cell(row=3, column=col_idx, value=group_cols[0].banner_label)
                cell.font = Font(bold=True, size=10, color="FFFFFF")
                cell.fill = BANNER_GROUP_FILL
                cell.alignment = CENTER
                if len(group_cols) > 1:
                    ws.merge_cells(start_row=3, start_column=col_idx, end_row=3, end_column=col_idx + len(group_cols) - 1)
                col_idx += len(group_cols)
        header_row_offset = 1
    else:
        header_row_offset = 0

    row_labels = 3 + header_row_offset  # Column value labels
    row_letters = 4 + header_row_offset  # Letters
    row_base_w = 5 + header_row_offset  # Base (weighted or only)
    has_dual_base = spec.weight is not None
    row_base_uw = (6 + header_row_offset) if has_dual_base else None
    data_start = (7 if has_dual_base else 6) + header_row_offset

    # Row: Column value labels
    for i, bc in enumerate(banner_columns):
        cell = ws.cell(row=row_labels, column=2 + i, value=bc.value_label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = HEADER_BORDER
    cell = ws.cell(row=row_labels, column=total_col, value="Total")
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = CENTER

    # Row: Letters
    for i, bc in enumerate(banner_columns):
        cell = ws.cell(row=row_letters, column=2 + i, value=bc.letter)
        cell.font = Font(bold=True, size=10, color="FFFFFF")
        cell.fill = LETTER_HEADER_FILL
        cell.alignment = CENTER

    # Row: Base (weighted) — compute from data
    base_label = "Base (weighted)" if has_dual_base else "Base (N)"
    ws.cell(row=row_base_w, column=1, value=base_label).font = BASE_FONT
    grand_total = 0
    col_bases = {}  # letter -> weighted count
    col_bases_uw = {}  # letter -> unweighted count

    for bc in banner_columns:
        ct = all_ct.get(bc.banner_var, {})
        table = ct.get("table", [])
        w_total = sum(
            row_data.get(bc.value, {}).get("count", 0)
            for row_data in table if isinstance(row_data.get(bc.value), dict)
        )
        col_bases[bc.letter] = w_total
        grand_total += w_total

        # Unweighted base
        if has_dual_base:
            mask = data.df[bc.banner_var] == float(bc.value) if bc.value.replace('.', '', 1).replace('-', '', 1).isdigit() else data.df[bc.banner_var] == bc.value
            col_bases_uw[bc.letter] = int(mask.sum())

    for i, bc in enumerate(banner_columns):
        cell = ws.cell(row=row_base_w, column=2 + i, value=int(round(col_bases.get(bc.letter, 0))))
        cell.font = BASE_FONT
        cell.alignment = CENTER
        cell.fill = TOTAL_FILL
    # Grand total
    cell = ws.cell(row=row_base_w, column=total_col, value=int(round(grand_total)))
    cell.font = BASE_FONT
    cell.alignment = CENTER
    cell.fill = TOTAL_FILL

    # Row: Base (unweighted) — T1-4
    if has_dual_base:
        ws.cell(row=row_base_uw, column=1, value="Base (unweighted)").font = Font(bold=True, size=9, color="9CA3AF")
        total_uw = 0
        for i, bc in enumerate(banner_columns):
            uw = col_bases_uw.get(bc.letter, 0)
            total_uw += uw
            cell = ws.cell(row=row_base_uw, column=2 + i, value=uw)
            cell.font = Font(size=9, color="9CA3AF")
            cell.alignment = CENTER
        cell = ws.cell(row=row_base_uw, column=total_col, value=total_uw)
        cell.font = Font(size=9, color="9CA3AF")
        cell.alignment = CENTER

    # ── Data rows ──
    # Collect all unique row values/labels across all banner crosstabs
    all_rows = []
    seen_rv = set()
    for banner_var in banners:
        ct = all_ct.get(banner_var, {})
        for row_data in ct.get("table", []):
            rv = row_data.get("row_value")
            if rv not in seen_rv:
                seen_rv.add(rv)
                all_rows.append({"row_value": rv, "row_label": row_data.get("row_label", str(rv))})

    current_row = data_start
    for row_info in all_rows:
        rv = row_info["row_value"]
        ws.cell(row=current_row, column=1, value=row_info["row_label"]).font = LABEL_FONT
        ws.cell(row=current_row, column=1).alignment = LEFT

        row_total_count = 0
        for i, bc in enumerate(banner_columns):
            ct = all_ct.get(bc.banner_var, {})
            # Find this row in the crosstab
            cell_data = None
            for rd in ct.get("table", []):
                if rd.get("row_value") == rv:
                    cell_data = rd.get(bc.value, {})
                    break
            if not isinstance(cell_data, dict):
                ws.cell(row=current_row, column=2 + i, value="-").font = COUNT_FONT
                ws.cell(row=current_row, column=2 + i).alignment = CENTER
                continue

            count = cell_data.get("count", 0)
            pct = cell_data.get("percentage", 0)
            orig_sig = cell_data.get("significance_letters", [])
            row_total_count += count

            # Remap sig letters from per-banner letters to global letters
            ct_col_labels = ct.get("col_labels", {})
            # Build reverse map: original letter -> value
            orig_letter_to_value = {v: k for k, v in ct_col_labels.items()}
            # Map to global letters
            global_sig = []
            for orig_letter in orig_sig:
                orig_value = orig_letter_to_value.get(orig_letter)
                if orig_value:
                    for gbc in banner_columns:
                        if gbc.banner_var == bc.banner_var and gbc.value == orig_value:
                            global_sig.append(gbc.letter)
                            break

            col_idx = 2 + i
            if spec.show_percentages:
                pct_str = f"{pct:.1f}%"
                if global_sig:
                    pct_str += " " + "".join(global_sig)
                    cell = ws.cell(row=current_row, column=col_idx, value=pct_str)
                    cell.font = SIG_FONT
                else:
                    cell = ws.cell(row=current_row, column=col_idx, value=pct_str)
                    cell.font = PCT_FONT
                cell.alignment = CENTER

        # Total
        if grand_total > 0:
            total_pct = round(row_total_count / grand_total * 100, 1)
            cell = ws.cell(row=current_row, column=total_col, value=f"{total_pct:.1f}%")
            cell.font = PCT_FONT
            cell.alignment = CENTER
            cell.fill = TOTAL_FILL

        for c in range(1, total_col + 1):
            ws.cell(row=current_row, column=c).border = THIN_BORDER
        current_row += 1

    # ── Nets ──
    var_nets = (spec.nets or {}).get(sheet_result.variable, {})
    if var_nets:
        current_row += 1
        ws.cell(row=current_row, column=1, value="Nets").font = Font(bold=True, size=10, color="166534")
        current_row += 1
        for net_name, net_values in var_nets.items():
            ws.cell(row=current_row, column=1, value=net_name).font = Font(bold=True, size=10, color="166534")
            ws.cell(row=current_row, column=1).fill = NET_FILL

            net_grand = 0
            for i, bc in enumerate(banner_columns):
                ct = all_ct.get(bc.banner_var, {})
                net_count = 0
                col_base = col_bases.get(bc.letter, 0)
                for rd in ct.get("table", []):
                    rv = rd.get("row_value")
                    if rv in net_values or (isinstance(rv, float) and int(rv) in net_values):
                        cd = rd.get(bc.value, {})
                        if isinstance(cd, dict):
                            net_count += cd.get("count", 0)
                net_grand += net_count
                net_pct = round(net_count / col_base * 100, 1) if col_base > 0 else 0
                cell = ws.cell(row=current_row, column=2 + i, value=f"{net_pct:.1f}%")
                cell.font = Font(size=10, color="166534")
                cell.fill = NET_FILL
                cell.alignment = CENTER

            if grand_total > 0:
                cell = ws.cell(row=current_row, column=total_col, value=f"{round(net_grand / grand_total * 100, 1):.1f}%")
                cell.font = Font(size=10, color="166534")
                cell.fill = NET_FILL
                cell.alignment = CENTER
            current_row += 1

    # ── Means with T-test (T1-1) ──
    if spec.include_means and not sheet_result.is_mrs:
        stub_var = sheet_result.variable
        if pd.api.types.is_numeric_dtype(data.df[stub_var]):
            current_row += 1
            ws.cell(row=current_row, column=1, value="Statistics").font = Font(bold=True, size=10, color="9A3412")
            current_row += 1
            alpha = 1 - spec.significance_level

            # Compute means per banner group
            for b_idx, banner_var in enumerate(banners):
                group_cols = [bc for bc in banner_columns if bc.banner_index == b_idx]
                col_vals = [float(bc.value) if bc.value.replace('.', '', 1).replace('-', '', 1).isdigit() else bc.value for bc in group_cols]
                means_result = _compute_means_by_column(data.df, stub_var, banner_var, col_vals, spec.weight, alpha)

                # Mean row
                ws.cell(row=current_row, column=1, value="Mean").font = MEAN_FONT
                ws.cell(row=current_row, column=1).fill = MEAN_FILL
                for bc in group_cols:
                    col_i = banner_columns.index(bc)
                    mr = means_result.get(str(float(bc.value) if bc.value.replace('.', '', 1).replace('-', '', 1).isdigit() else bc.value), {})
                    m = mr.get("mean")
                    if m is None:
                        cell = ws.cell(row=current_row, column=2 + col_i, value="-")
                    else:
                        sig = mr.get("sig_letters", [])
                        # Remap to global letters
                        global_sig = []
                        for sl in sig:
                            for gbc in group_cols:
                                if gbc.letter == sl or (hasattr(gbc, '_local_letter') and gbc._local_letter == sl):
                                    global_sig.append(gbc.letter)
                                    break
                            else:
                                # Try matching by index
                                idx = ord(sl) - ord('A')
                                if 0 <= idx < len(group_cols):
                                    global_sig.append(group_cols[idx].letter)

                        mean_str = f"{m:.2f}"
                        if global_sig:
                            mean_str += " " + "".join(global_sig)
                            cell = ws.cell(row=current_row, column=2 + col_i, value=mean_str)
                            cell.font = MEAN_SIG_FONT
                        else:
                            cell = ws.cell(row=current_row, column=2 + col_i, value=mean_str)
                            cell.font = MEAN_FONT
                    cell.fill = MEAN_FILL
                    cell.alignment = CENTER

                # Total mean
                total_vals = data.df[stub_var].dropna()
                if len(total_vals) > 0:
                    if spec.weight and spec.weight in data.df.columns:
                        tw = data.df[spec.weight].loc[total_vals.index]
                        total_mean = float(np.average(total_vals, weights=tw))
                    else:
                        total_mean = float(total_vals.mean())
                    cell = ws.cell(row=current_row, column=total_col, value=f"{total_mean:.2f}")
                    cell.font = MEAN_FONT
                    cell.fill = MEAN_FILL
                    cell.alignment = CENTER

            current_row += 1

            # Std Dev row
            ws.cell(row=current_row, column=1, value="Std Dev").font = Font(size=9, color="9A3412")
            ws.cell(row=current_row, column=1).fill = MEAN_FILL
            for bc in banner_columns:
                col_i = banner_columns.index(bc)
                cv_float = float(bc.value) if bc.value.replace('.', '', 1).replace('-', '', 1).isdigit() else bc.value
                means_result = _compute_means_by_column(data.df, stub_var, bc.banner_var, [cv_float], spec.weight, alpha)
                mr = means_result.get(str(cv_float), {})
                std = mr.get("std")
                cell = ws.cell(row=current_row, column=2 + col_i, value=f"{std:.2f}" if std is not None else "-")
                cell.font = Font(size=9, color="9A3412")
                cell.fill = MEAN_FILL
                cell.alignment = CENTER
            current_row += 1

    # Column widths
    ws.column_dimensions["A"].width = 40
    for i in range(n_banner_cols + 1):
        ws.column_dimensions[get_column_letter(2 + i)].width = 16
    ws.freeze_panes = f"B{data_start}"
