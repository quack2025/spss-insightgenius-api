"""MCP (Model Context Protocol) server for SPSS InsightGenius.

Exposes SPSS analysis capabilities as MCP tools via SSE transport.
Mounted at /mcp/ in the main FastAPI app.

Authentication: pass your API key as the `api_key` parameter in each tool call.
SSE endpoint:   GET  /mcp/sse
Message post:   POST /mcp/messages/

Usage with automation tools (n8n, Make, Zapier):
  Connect to: https://spss.insightgenius.io/mcp/sse
  Then call tools with your api_key as a parameter.

All file data is passed as base64-encoded strings — this API is stateless.
"""

import base64
import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from auth import get_key_config
from middleware.processing import run_in_executor
from services.converter import FormatConverter
from services.quantipy_engine import QuantiProEngine
from services.tabulation_builder import TabulateSpec, build_tabulation

logger = logging.getLogger(__name__)

# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "SPSS InsightGenius",
    description=(
        "MCP server for SPSS (.sav) file processing and market research analysis. "
        "Provides tools for metadata extraction, frequency tables, crosstabs with "
        "significance testing (A/B/C letters), and full tabulation to Excel.\n\n"
        "All tools require an `api_key` parameter (sk_test_... or sk_live_...). "
        "SPSS file content is passed as base64-encoded strings."
    ),
)


# ── Auth + file helpers ───────────────────────────────────────────────────────

def _auth(api_key: str):
    """Validate API key, raise ToolError on failure."""
    try:
        return get_key_config(api_key)
    except ValueError as e:
        raise ToolError(str(e))


def _decode_spss(file_base64: str) -> bytes:
    """Decode base64 SPSS file data, raise ToolError if malformed."""
    try:
        return base64.b64decode(file_base64)
    except Exception:
        raise ToolError(
            "Invalid base64 encoding for file_base64. "
            "Encode the .sav file bytes with standard base64."
        )


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_spss_metadata(
    api_key: str,
    file_base64: str,
    filename: str = "upload.sav",
) -> dict[str, Any]:
    """Extract metadata from an SPSS file.

    Returns variable names, labels, types, value labels, auto-detected question
    types (categorical/scale/dichotomy/open), and likely weight variables.

    Args:
        api_key:     Your API key (sk_test_... or sk_live_...).
        file_base64: Base64-encoded content of the .sav file.
        filename:    Original filename — used only for format detection (default: upload.sav).
    """
    _auth(api_key)
    file_bytes = _decode_spss(file_base64)
    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
        result = await run_in_executor(QuantiProEngine.extract_metadata, data)
    except (ToolError, Exception) as e:
        if isinstance(e, ToolError):
            raise
        raise ToolError(f"Failed to process SPSS file: {e}")
    return result


@mcp.tool()
async def get_variable_info(
    api_key: str,
    file_base64: str,
    variables: list[str],
    filename: str = "upload.sav",
) -> list[dict[str, Any]]:
    """Get detailed information about specific variables in an SPSS file.

    Returns name, label, data type, value labels, and auto-detected question
    type for each requested variable.

    Args:
        api_key:     Your API key.
        file_base64: Base64-encoded .sav file content.
        variables:   List of variable names to retrieve info for.
        filename:    Original filename (default: upload.sav).
    """
    _auth(api_key)
    file_bytes = _decode_spss(file_base64)
    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
        result = await run_in_executor(QuantiProEngine.extract_metadata, data)
    except (ToolError, Exception) as e:
        if isinstance(e, ToolError):
            raise
        raise ToolError(f"Failed to process SPSS file: {e}")

    var_map = {v["name"]: v for v in result.get("variables", [])}
    missing = [v for v in variables if v not in var_map]
    if missing:
        available = list(var_map.keys())[:30]
        raise ToolError(
            f"Variables not found: {missing}. "
            f"Available (first 30): {available}"
        )
    return [var_map[v] for v in variables]


@mcp.tool()
async def analyze_frequencies(
    api_key: str,
    file_base64: str,
    variable: str,
    weight: str | None = None,
    filename: str = "upload.sav",
) -> dict[str, Any]:
    """Run frequency analysis on a single variable in an SPSS file.

    Returns a frequency table with value labels, counts, percentages, and
    valid percentages (excluding missing / system missing).

    Args:
        api_key:     Your API key.
        file_base64: Base64-encoded .sav file content.
        variable:    Variable name to analyze.
        weight:      Optional weight variable name.
        filename:    Original filename (default: upload.sav).
    """
    _auth(api_key)
    file_bytes = _decode_spss(file_base64)
    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
    except Exception as e:
        raise ToolError(f"Failed to load SPSS file: {e}")
    try:
        result = await run_in_executor(QuantiProEngine.frequency, data, variable, weight)
    except ValueError as e:
        raise ToolError(str(e))
    except Exception as e:
        raise ToolError(f"Frequency analysis failed: {e}")
    return result


@mcp.tool()
async def analyze_crosstabs(
    api_key: str,
    file_base64: str,
    row_variable: str,
    col_variable: str,
    weight: str | None = None,
    significance_level: float = 0.95,
    filename: str = "upload.sav",
) -> dict[str, Any]:
    """Run crosstab analysis between two variables with significance testing.

    Uses column proportion z-tests to assign significance letters (A, B, C, …)
    to banner columns. A letter appears in a cell when this column's proportion
    is significantly higher than the lettered column's (p < 1 - significance_level).

    Unweighted tests use statsmodels proportions_ztest.
    Weighted tests apply Kish effective-n design effect.

    Args:
        api_key:            Your API key.
        file_base64:        Base64-encoded .sav file content.
        row_variable:       Row (stub) variable name.
        col_variable:       Column (banner) variable name.
        weight:             Optional weight variable name.
        significance_level: Confidence threshold, e.g. 0.95 for 95% (default).
        filename:           Original filename (default: upload.sav).
    """
    _auth(api_key)
    file_bytes = _decode_spss(file_base64)
    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
    except Exception as e:
        raise ToolError(f"Failed to load SPSS file: {e}")
    try:
        result = await run_in_executor(
            QuantiProEngine.crosstab_with_significance,
            data, row_variable, col_variable, weight, significance_level,
        )
    except ValueError as e:
        raise ToolError(str(e))
    except Exception as e:
        raise ToolError(f"Crosstab analysis failed: {e}")
    return result


@mcp.tool()
async def export_data(
    api_key: str,
    file_base64: str,
    target_format: str = "csv",
    apply_labels: bool = True,
    include_metadata_sheet: bool = True,
    filename: str = "upload.sav",
) -> dict[str, Any]:
    """Export SPSS data to another format.

    Converts the .sav file to xlsx, csv, dta (Stata), or parquet.
    The converted file is returned as base64-encoded data in the `data_base64` field.

    Args:
        api_key:                Your API key.
        file_base64:            Base64-encoded .sav file content.
        target_format:          Output format — "xlsx", "csv", "dta", or "parquet".
        apply_labels:           Replace numeric codes with value labels (default True).
        include_metadata_sheet: Add a variable-labels sheet to Excel output (default True).
        filename:               Original filename (default: upload.sav).
    """
    _auth(api_key)
    valid_formats = {"xlsx", "csv", "dta", "parquet"}
    if target_format not in valid_formats:
        raise ToolError(
            f"Invalid target_format '{target_format}'. "
            f"Accepted: {', '.join(sorted(valid_formats))}"
        )
    file_bytes = _decode_spss(file_base64)
    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
    except Exception as e:
        raise ToolError(f"Failed to load SPSS file: {e}")
    try:
        output_bytes, content_type, extension = await run_in_executor(
            FormatConverter.convert,
            data.df, data.meta, target_format, apply_labels, include_metadata_sheet,
        )
    except Exception as e:
        raise ToolError(f"Export failed: {e}")

    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
    return {
        "filename": f"{base_name}{extension}",
        "content_type": content_type,
        "data_base64": base64.b64encode(output_bytes).decode(),
        "size_bytes": len(output_bytes),
    }


@mcp.tool()
async def create_tabulation(
    api_key: str,
    file_base64: str,
    banner: str,
    stubs: list[str] | None = None,
    significance_level: float = 0.95,
    weight: str | None = None,
    title: str = "",
    filename: str = "upload.sav",
) -> dict[str, Any]:
    """Create a full tabulation Excel workbook with crosstabs and significance letters.

    Generates a professional .xlsx workbook:
    - Summary sheet: column legend (letter → label) + stub index
    - One sheet per stub variable with column percentages + significance letters
    - Column bases (N)
    - Top/Bottom 2 Box nets (if applicable)

    Pass stubs=null (or omit) to auto-select all variables that have value labels.
    The returned Excel is base64-encoded in the `data_base64` field.

    Args:
        api_key:            Your API key.
        file_base64:        Base64-encoded .sav file content.
        banner:             Banner variable name (the demographic to cross against).
        stubs:              List of stub variable names, or null for all.
        significance_level: Confidence threshold (default 0.95).
        weight:             Optional weight variable name.
        title:              Report title shown in the Excel Summary sheet.
        filename:           Original filename (default: upload.sav).
    """
    _auth(api_key)
    file_bytes = _decode_spss(file_base64)
    try:
        data = await run_in_executor(QuantiProEngine.load_spss, file_bytes, filename)
    except Exception as e:
        raise ToolError(f"Failed to load SPSS file: {e}")

    if banner not in data.df.columns:
        available = list(data.df.columns[:20])
        raise ToolError(
            f"Banner variable '{banner}' not found. "
            f"Available (first 20): {available}"
        )

    if stubs and stubs != ["_all_"]:
        missing_stubs = [s for s in stubs if s not in data.df.columns]
        if missing_stubs:
            raise ToolError(f"Stub variables not found: {missing_stubs}")

    tab_spec = TabulateSpec(
        banner=banner,
        stubs=stubs if stubs else ["_all_"],
        weight=weight,
        significance_level=significance_level,
        title=title,
    )
    try:
        result = await run_in_executor(build_tabulation, QuantiProEngine, data, tab_spec)
    except Exception as e:
        raise ToolError(f"Tabulation failed: {e}")

    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
    return {
        "filename": f"tabulation_{banner}_{base_name}.xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "data_base64": base64.b64encode(result.excel_bytes).decode(),
        "stubs_processed": result.successful,
        "stubs_failed": result.failed,
        "total_stubs": result.total_stubs,
    }


@mcp.tool()
async def list_files(api_key: str) -> dict[str, Any]:
    """Return API capabilities and connection info for the authenticated user.

    Note: this API is stateless — no files are stored between calls.
    This tool validates your API key and returns your plan info and available tools.

    Args:
        api_key: Your API key.
    """
    key_config = _auth(api_key)
    return {
        "server": "SPSS InsightGenius MCP Server",
        "key_name": key_config.name,
        "plan": key_config.plan,
        "scopes": key_config.scopes,
        "stateless": True,
        "note": (
            "This API is stateless. SPSS files are not stored between calls — "
            "pass file content as base64 in each tool call."
        ),
        "available_tools": [
            {
                "name": "get_spss_metadata",
                "description": "Extract variable metadata (names, labels, types, value labels)",
            },
            {
                "name": "get_variable_info",
                "description": "Get details for specific variables by name",
            },
            {
                "name": "analyze_frequencies",
                "description": "Frequency table with counts and percentages for one variable",
            },
            {
                "name": "analyze_crosstabs",
                "description": "Crosstab with significance letters (A/B/C) for two variables",
            },
            {
                "name": "export_data",
                "description": "Convert .sav to xlsx / csv / dta / parquet (returns base64)",
            },
            {
                "name": "create_tabulation",
                "description": "Full tabulation Excel workbook (multi-sheet, sig letters, nets)",
            },
        ],
    }


# ── ASGI app factory ──────────────────────────────────────────────────────────

def get_mcp_asgi_app():
    """Return the MCP SSE ASGI app for mounting in the main FastAPI app.

    SSE endpoint:  GET  /mcp/sse
    Post endpoint: POST /mcp/messages/
    """
    return mcp.sse_app()
