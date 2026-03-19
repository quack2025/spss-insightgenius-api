"""Tabulation Excel builder — professional market research crosstab tables.

Generates an .xlsx workbook where each sheet is one stub variable crossed by a banner,
with significance letters, nets, column bases, and proper formatting.

Output mirrors what WinCross / PSPP / Quantum produce.
"""

import io
import logging
import string
from dataclasses import dataclass, field
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

# ── Styling ──────────────────────────────────────────────────────────────────

TITLE_FONT = Font(bold=True, size=12, color="1F2937")
HEADER_FONT = Font(bold=True, size=10, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
LETTER_HEADER_FILL = PatternFill(start_color="1D4ED8", end_color="1D4ED8", fill_type="solid")
TOTAL_FILL = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")
NET_FILL = PatternFill(start_color="F0FDF4", end_color="F0FDF4", fill_type="solid")
SIG_FONT = Font(bold=True, size=9, color="DC2626")  # Red for significance letters
BASE_FONT = Font(bold=True, size=10, color="6B7280")
LABEL_FONT = Font(size=10, color="1F2937")
PCT_FONT = Font(size=10, color="374151")
COUNT_FONT = Font(size=9, color="9CA3AF")
THIN_BORDER = Border(
    bottom=Side(style="thin", color="E5E7EB"),
)
HEADER_BORDER = Border(
    bottom=Side(style="medium", color="1D4ED8"),
)
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")
WRAP = Alignment(wrap_text=True, vertical="top")


@dataclass
class TabulateSpec:
    """Specification for a full tabulation run."""
    banner: str  # Column variable (demographic)
    stubs: list[str]  # Row variables to tabulate (or ["_all_"] for auto)
    weight: str | None = None
    significance_level: float = 0.95
    nets: dict[str, dict[str, list[Any]]] | None = None  # per-variable nets: {"Q1": {"T2B": [4,5]}}
    show_counts: bool = True
    show_percentages: bool = True
    title: str = ""


@dataclass
class SheetResult:
    """Result for one stub variable."""
    variable: str
    label: str | None
    status: str  # "success" | "error"
    error: str | None = None
    crosstab_data: dict[str, Any] | None = None


@dataclass
class TabulationResult:
    """Full tabulation result."""
    banner: str
    banner_label: str | None
    total_stubs: int
    successful: int
    failed: int
    sheets: list[SheetResult] = field(default_factory=list)
    excel_bytes: bytes = b""


def build_tabulation(
    engine_cls: Any,
    data: Any,
    spec: TabulateSpec,
) -> TabulationResult:
    """Run all crosstabs and build the Excel workbook.

    This is CPU-bound — call via asyncio.to_thread().
    """
    from services.quantipy_engine import QuantiProEngine, SPSSData

    df = data.df
    meta = data.meta
    col_labels = getattr(meta, "column_names_to_labels", {})

    # Resolve stubs
    if spec.stubs == ["_all_"] or not spec.stubs:
        # Auto-select: all variables with value labels except the banner itself
        value_labels = getattr(meta, "variable_value_labels", {})
        stubs = [
            col for col in df.columns
            if col != spec.banner
            and col in value_labels
            and len(value_labels.get(col, {})) >= 2
        ]
        if not stubs:
            # Fallback: all numeric variables
            stubs = [
                col for col in df.columns
                if col != spec.banner and df[col].dtype.kind in ("i", "f")
            ]
    else:
        stubs = spec.stubs

    result = TabulationResult(
        banner=spec.banner,
        banner_label=col_labels.get(spec.banner, spec.banner),
        total_stubs=len(stubs),
        successful=0,
        failed=0,
    )

    # Run crosstabs
    for stub in stubs:
        try:
            ct = QuantiProEngine.crosstab_with_significance(
                data, row=stub, col=spec.banner,
                weight=spec.weight,
                significance_level=spec.significance_level,
            )
            sheet = SheetResult(
                variable=stub,
                label=col_labels.get(stub, stub),
                status="success",
                crosstab_data=ct,
            )
            result.successful += 1
        except Exception as e:
            sheet = SheetResult(
                variable=stub,
                label=col_labels.get(stub, stub),
                status="error",
                error=str(e),
            )
            result.failed += 1
        result.sheets.append(sheet)

    # Build Excel
    result.excel_bytes = _build_excel(result, spec, data)
    return result


def _build_excel(result: TabulationResult, spec: TabulateSpec, data: Any) -> bytes:
    """Build the professional tabulation workbook."""
    wb = Workbook()

    # ── Summary sheet ──
    ws_summary = wb.active
    ws_summary.title = "Summary"
    _write_summary_sheet(ws_summary, result, spec, data)

    # ── One sheet per stub ──
    for sheet_result in result.sheets:
        if sheet_result.status != "success" or not sheet_result.crosstab_data:
            continue

        # Sheet name: variable name truncated to 31 chars (Excel limit)
        sheet_name = sheet_result.variable[:31]
        # Avoid duplicate sheet names
        existing = [ws.title for ws in wb.worksheets]
        if sheet_name in existing:
            sheet_name = sheet_name[:28] + "_" + str(existing.count(sheet_name))

        ws = wb.create_sheet(title=sheet_name)
        _write_crosstab_sheet(
            ws, sheet_result, spec, data,
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _write_summary_sheet(ws, result: TabulationResult, spec: TabulateSpec, data: Any):
    """Write the summary/index sheet."""
    meta = data.meta
    col_labels = getattr(meta, "column_names_to_labels", {})

    # Title
    title = spec.title or f"Tabulation Report"
    ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=16, color="1F2937")
    ws.merge_cells("A1:E1")

    # Metadata
    r = 3
    info = [
        ("File", data.file_name),
        ("Cases", len(data.df)),
        ("Banner", f"{spec.banner} ({col_labels.get(spec.banner, '')})"),
        ("Weight", spec.weight or "(none)"),
        ("Significance Level", f"{spec.significance_level:.0%}"),
        ("Total Stubs", result.total_stubs),
        ("Successful", result.successful),
        ("Failed", result.failed),
    ]
    for label, value in info:
        ws.cell(row=r, column=1, value=label).font = Font(bold=True, size=10)
        ws.cell(row=r, column=2, value=str(value)).font = Font(size=10)
        r += 1

    # Banner column legend
    r += 1
    ws.cell(row=r, column=1, value="Column Legend").font = Font(bold=True, size=11)
    r += 1
    headers = ["Letter", "Value", "Label", "N"]
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=r, column=c, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
    r += 1

    # Get banner value labels from first successful crosstab
    for sheet in result.sheets:
        if sheet.status == "success" and sheet.crosstab_data:
            ct = sheet.crosstab_data
            col_letter_map = ct.get("col_labels", {})
            col_vl_map = ct.get("col_value_labels", {})
            # Sort by letter
            for val, letter in sorted(col_letter_map.items(), key=lambda x: x[1]):
                ws.cell(row=r, column=1, value=letter).font = Font(bold=True, size=10)
                ws.cell(row=r, column=1).alignment = CENTER
                ws.cell(row=r, column=2, value=val)
                ws.cell(row=r, column=3, value=col_vl_map.get(val, val))
                # Count for this banner value
                col_total = 0
                for row_data in ct.get("table", []):
                    cell_data = row_data.get(val, {})
                    if isinstance(cell_data, dict):
                        col_total += cell_data.get("count", 0)
                ws.cell(row=r, column=4, value=int(round(col_total)))
                r += 1
            break

    # Stub index
    r += 1
    ws.cell(row=r, column=1, value="Stub Index").font = Font(bold=True, size=11)
    r += 1
    idx_headers = ["#", "Variable", "Label", "Status", "Sheet"]
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
        ws.cell(row=r, column=4, value=sheet.status)
        ws.cell(row=r, column=5, value=sheet.variable[:31] if sheet.status == "success" else "")
        if sheet.status == "error":
            ws.cell(row=r, column=4).font = Font(color="DC2626")
        r += 1

    # Auto-width
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 45
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 20


def _write_crosstab_sheet(ws, sheet_result: SheetResult, spec: TabulateSpec, data: Any):
    """Write one crosstab table to a worksheet.

    Layout:
    Row 1: Variable label (title)
    Row 2: Banner label
    Row 3: Column value labels
    Row 4: Column letters (A, B, C, ...)
    Row 5: Base (N)
    Row 6+: Data rows — each row shows label | pct [sig letters] per column
    Last rows: Nets (if defined)
    """
    ct = sheet_result.crosstab_data
    if not ct:
        return

    col_labels_map = ct.get("col_labels", {})  # {"1.0": "A", ...}
    col_vl_map = ct.get("col_value_labels", {})  # {"1.0": "Male", ...}
    table = ct.get("table", [])

    # Sort columns by letter
    sorted_cols = sorted(col_labels_map.items(), key=lambda x: x[1])
    col_values = [cv for cv, _ in sorted_cols]
    col_letters = [letter for _, letter in sorted_cols]
    n_cols = len(col_values)

    # Calculate column totals for bases
    col_totals = {}
    for cv in col_values:
        total = 0
        for row_data in table:
            cell_data = row_data.get(cv, {})
            if isinstance(cell_data, dict):
                total += cell_data.get("count", 0)
        col_totals[cv] = total

    # Row 1: Variable title
    title = f"{sheet_result.variable}"
    if sheet_result.label:
        title += f": {sheet_result.label}"
    ws.cell(row=1, column=1, value=title).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=1 + n_cols)

    # Row 2: Significance note
    sig_note = f"Significance: {ct.get('significance_level', 0.95):.0%} confidence"
    if spec.weight:
        sig_note += f" | Weighted by: {spec.weight}"
    ws.cell(row=2, column=1, value=sig_note).font = Font(italic=True, size=9, color="6B7280")

    # Row 3: Column value labels
    ws.cell(row=3, column=1, value="").font = HEADER_FONT
    for i, cv in enumerate(col_values):
        cell = ws.cell(row=3, column=2 + i, value=col_vl_map.get(cv, cv))
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = HEADER_BORDER
    # Total column
    total_col = 2 + n_cols
    cell = ws.cell(row=3, column=total_col, value="Total")
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = CENTER

    # Row 4: Column letters
    ws.cell(row=4, column=1, value="").font = HEADER_FONT
    for i, letter in enumerate(col_letters):
        cell = ws.cell(row=4, column=2 + i, value=letter)
        cell.font = Font(bold=True, size=10, color="FFFFFF")
        cell.fill = LETTER_HEADER_FILL
        cell.alignment = CENTER

    # Row 5: Base (N)
    ws.cell(row=5, column=1, value="Base (N)").font = BASE_FONT
    grand_total = 0
    for i, cv in enumerate(col_values):
        base = col_totals.get(cv, 0)
        grand_total += base
        cell = ws.cell(row=5, column=2 + i, value=int(round(base)))
        cell.font = BASE_FONT
        cell.alignment = CENTER
        cell.fill = TOTAL_FILL
    cell = ws.cell(row=5, column=total_col, value=int(round(grand_total)))
    cell.font = BASE_FONT
    cell.alignment = CENTER
    cell.fill = TOTAL_FILL

    # Data rows (row 6+)
    current_row = 6
    row_value_labels = getattr(data.meta, "variable_value_labels", {}).get(sheet_result.variable, {})

    for row_data in table:
        row_label = row_data.get("row_label", str(row_data.get("row_value", "")))
        ws.cell(row=current_row, column=1, value=row_label).font = LABEL_FONT
        ws.cell(row=current_row, column=1).alignment = LEFT

        row_total_count = 0
        row_total_pct_num = 0  # weighted sum for total pct

        for i, cv in enumerate(col_values):
            cell_data = row_data.get(cv, {})
            if not isinstance(cell_data, dict):
                current_row += 1
                continue

            count = cell_data.get("count", 0)
            pct = cell_data.get("percentage", 0)
            sig_letters = cell_data.get("significance_letters", [])
            row_total_count += count

            col_idx = 2 + i

            if spec.show_percentages:
                # Write percentage with sig letters
                pct_str = f"{pct:.1f}%"
                if sig_letters:
                    pct_str += " " + "".join(sig_letters)
                    cell = ws.cell(row=current_row, column=col_idx, value=pct_str)
                    cell.font = SIG_FONT
                else:
                    cell = ws.cell(row=current_row, column=col_idx, value=pct_str)
                    cell.font = PCT_FONT
                cell.alignment = CENTER

            elif spec.show_counts:
                cell = ws.cell(row=current_row, column=col_idx, value=int(round(count)))
                cell.font = COUNT_FONT
                cell.alignment = CENTER

        # Total column: overall percentage
        if grand_total > 0:
            total_pct = round(row_total_count / grand_total * 100, 1)
            cell = ws.cell(row=current_row, column=total_col, value=f"{total_pct:.1f}%")
            cell.font = PCT_FONT
            cell.alignment = CENTER
            cell.fill = TOTAL_FILL

        # Thin border
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

            net_total_count = 0
            for i, cv in enumerate(col_values):
                # Sum counts for net values in this column
                net_count = 0
                col_base = col_totals.get(cv, 0)
                for row_data in table:
                    rv = row_data.get("row_value")
                    if rv in net_values or (isinstance(rv, float) and int(rv) in net_values):
                        cell_data = row_data.get(cv, {})
                        if isinstance(cell_data, dict):
                            net_count += cell_data.get("count", 0)

                net_total_count += net_count
                net_pct = round(net_count / col_base * 100, 1) if col_base > 0 else 0
                cell = ws.cell(row=current_row, column=2 + i, value=f"{net_pct:.1f}%")
                cell.font = Font(size=10, color="166534")
                cell.fill = NET_FILL
                cell.alignment = CENTER

            # Total column for net
            if grand_total > 0:
                net_total_pct = round(net_total_count / grand_total * 100, 1)
                cell = ws.cell(row=current_row, column=total_col, value=f"{net_total_pct:.1f}%")
                cell.font = Font(size=10, color="166534")
                cell.fill = NET_FILL
                cell.alignment = CENTER

            current_row += 1

    # ── Column widths ──
    ws.column_dimensions["A"].width = 40  # Row labels
    for i in range(n_cols + 1):  # data cols + total
        ws.column_dimensions[get_column_letter(2 + i)].width = 16

    # Freeze panes: freeze row labels + header rows
    ws.freeze_panes = "B6"
