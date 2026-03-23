"""MCP v2 server for SPSS InsightGenius.

Exposes 13 SPSS analysis tools via MCP with file session support (Redis).
Mounted at /mcp/ in the main FastAPI app.

Authentication: pass your API key as the `api_key` parameter in each tool call.
SSE endpoint:   GET  /mcp/sse
Message post:   POST /mcp/messages/

Usage with automation tools (n8n, Make, Zapier):
  Connect to: https://spss.insightgenius.io/mcp/sse
  Then call tools with your api_key as a parameter.

File sessions (v2):
  Upload once with spss_upload_file -> get a file_id.
  Pass file_id in subsequent calls to avoid re-uploading.
  Sessions have a 30-minute sliding TTL (configurable via SPSS_SESSION_TTL_SECONDS).
  Falls back to inline base64 if file_id is not provided.

Cross-replica sessions (Railway numReplicas > 1):
  SSE connections are pinned to one replica. POST /messages/ may land on a
  different replica that doesn't own the session. We fix this with a Redis
  pub/sub relay: the receiving replica publishes the message body to
  `mcp:msg:{session_id}`, and the owning replica's subscriber forwards it
  into the local in-memory stream. Requires REDIS_URL env var.

Sprint 3 planned: Streamable HTTP transport, transport-level auth.
"""

import asyncio
import base64
import logging
import uuid as uuid_mod
from typing import Any
from uuid import UUID

import mcp.types as types
import redis.asyncio as aioredis
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.server.sse import SseServerTransport
from mcp.shared.message import SessionMessage
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from auth import get_key_config
from config import get_settings
from middleware.processing import run_in_executor
from routers.downloads import store_download
from services.converter import FormatConverter
from services.quantipy_engine import QUANTIPYMRX_AVAILABLE, QuantiProEngine, SPSSData
from services.response_formatter import build_mcp_response
from services.tabulation_builder import TabulateSpec, build_tabulation

logger = logging.getLogger(__name__)

# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "SPSS InsightGenius",
    instructions=(
        "MCP server for SPSS (.sav) file processing and market research analysis.\n\n"
        "**File sessions (recommended):** Call `spss_upload_file` once to upload your "
        "data file and receive a `file_id`. Then pass that `file_id` to all subsequent "
        "tools — no need to re-upload the file each time. Sessions last 30 minutes "
        "(sliding window: each tool call resets the timer).\n\n"
        "**Inline mode (backwards compatible):** You can still pass `file_base64` directly "
        "to any tool if you prefer stateless calls.\n\n"
        "All tools require an `api_key` parameter (sk_test_... or sk_live_...). "
        "Responses include `insight_summary` (one-paragraph finding) and `content_blocks` "
        "(pre-digested data for presentations)."
    ),
)


# ── Auth + file helpers ───────────────────────────────────────────────────────

def _auth(api_key: str):
    """Validate API key, raise ToolError on failure."""
    try:
        return get_key_config(api_key)
    except ValueError as e:
        raise ToolError(str(e))


def _decode_base64(file_base64: str) -> bytes:
    """Decode base64 file data, raise ToolError if malformed."""
    try:
        return base64.b64decode(file_base64)
    except Exception:
        raise ToolError(
            "Invalid base64 encoding for file_base64. "
            "Encode the file bytes with standard base64."
        )


async def _get_redis() -> aioredis.Redis | None:
    """Get an async Redis client, or None if REDIS_URL is not configured."""
    settings = get_settings()
    if not settings.redis_url:
        return None
    return aioredis.from_url(settings.redis_url, decode_responses=False)


async def _resolve_file(
    file_id: str | None,
    file_base64: str | None,
    filename: str,
) -> tuple[bytes, str]:
    """Resolve file bytes from either a Redis session (file_id) or inline base64.

    Returns (file_bytes, format_str). Refreshes TTL on session access.
    Raises ToolError if neither source is available or data is invalid.
    """
    settings = get_settings()

    # Priority 1: file_id from Redis session
    if file_id:
        r = await _get_redis()
        if r is None:
            raise ToolError(
                "file_id requires Redis. Either configure REDIS_URL on the server "
                "or pass file_base64 directly."
            )
        try:
            file_key = f"spss:file:{file_id}"
            meta_key = f"spss:meta:{file_id}"
            file_bytes = await r.get(file_key)
            if not file_bytes:
                await r.aclose()
                raise ToolError(
                    f"File session '{file_id}' not found or expired. "
                    "Upload again with spss_upload_file."
                )
            meta_raw = await r.get(meta_key)
            # Refresh sliding TTL on both keys
            ttl = settings.spss_session_ttl_seconds
            await r.expire(file_key, ttl)
            await r.expire(meta_key, ttl)
            await r.aclose()

            if meta_raw:
                import json
                meta_info = json.loads(meta_raw)
                filename = meta_info.get("filename", filename)

            fmt = filename.rsplit(".", 1)[-1].lower() if "." in filename else "sav"
            return file_bytes, fmt
        except ToolError:
            raise
        except Exception as e:
            try:
                await r.aclose()
            except Exception:
                pass
            raise ToolError(f"Redis error retrieving file session: {e}")

    # Priority 2: inline base64
    if file_base64:
        file_bytes = _decode_base64(file_base64)
        fmt = filename.rsplit(".", 1)[-1].lower() if "." in filename else "sav"
        return file_bytes, fmt

    raise ToolError(
        "Either file_id (from spss_upload_file) or file_base64 is required."
    )


def _load_data(file_bytes: bytes, format_str: str, filename: str) -> SPSSData:
    """Load file bytes into SPSSData. Sprint 2: only .sav is supported.

    CPU-bound — call via run_in_executor.
    """
    if format_str != "sav":
        raise ToolError(
            f"Format '.{format_str}' is not yet supported. "
            "Currently only .sav (SPSS) files are accepted. "
            "CSV/Excel support comes in Sprint 3."
        )
    return QuantiProEngine.load_spss(file_bytes, filename)


def _extract_tables_summary(sheets: list) -> list[dict[str, Any]]:
    """Extract a JSON-friendly summary from TabulationResult.sheets.

    Design decision: Option B — extract summary from TabulationResult.sheets
    rather than refactoring the builder. This keeps the tabulation_builder
    unchanged and extracts what we need post-hoc.

    Each entry: {stub, stub_label, base_total, top_finding}
    """
    summary = []
    for sheet in sheets:
        if sheet.status != "success":
            continue
        entry: dict[str, Any] = {
            "stub": sheet.variable,
            "stub_label": sheet.label or sheet.variable,
            "base_total": None,
            "top_finding": "",
        }
        ct = sheet.crosstab_data
        if ct and isinstance(ct, dict):
            entry["base_total"] = ct.get("total_responses", ct.get("base", None))
            # Extract top finding from the data
            rows = ct.get("rows", ct.get("table", []))
            if rows and isinstance(rows, list) and len(rows) > 0:
                # Find row with highest total percentage
                best_row = None
                best_pct = -1
                for row in rows:
                    total_cell = row.get("Total", row.get("total", {}))
                    if isinstance(total_cell, dict):
                        pct = total_cell.get("percentage", 0)
                    elif isinstance(total_cell, (int, float)):
                        pct = total_cell
                    else:
                        pct = 0
                    if pct > best_pct:
                        best_pct = pct
                        best_row = row
                if best_row:
                    label = best_row.get("row_label", best_row.get("label", ""))
                    entry["top_finding"] = (
                        f"Most common: '{label}' ({best_pct:.1f}%)"
                        if best_pct > 0 else ""
                    )
        elif sheet.is_mrs and sheet.mrs_members:
            entry["top_finding"] = f"MRS group with {len(sheet.mrs_members)} items"
        elif sheet.is_grid and sheet.grid_data:
            n_vars = len(sheet.grid_data.get("variables", []))
            entry["top_finding"] = f"Grid summary with {n_vars} variables"

        summary.append(entry)
    return summary


# ── Tools ─────────────────────────────────────────────────────────────────────
# All tools use Pydantic input models from schemas/mcp_models.py via explicit
# parameters. Functions are defined as plain async callables so tests can import
# and call them directly.


# Tool 1: spss_upload_file ────────────────────────────────────────────────────

async def spss_upload_file(
    api_key: str,
    file_base64: str,
    filename: str = "upload.sav",
) -> dict[str, Any]:
    """Upload a data file to create a reusable file session.

    Stores the file in Redis with a 30-minute sliding TTL. Returns a file_id
    that you pass to all subsequent tools instead of re-uploading.

    Supported formats (Sprint 2): .sav only.
    Planned (Sprint 3): .csv, .tsv, .xlsx, .xls.

    Args:
        api_key:     Your API key (sk_test_... or sk_live_...).
        file_base64: Base64-encoded file contents.
        filename:    Original filename with extension (e.g., 'survey.sav').
    """
    _auth(api_key)
    file_bytes = _decode_base64(file_base64)

    settings = get_settings()
    max_bytes = settings.redis_max_file_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ToolError(
            f"File too large ({len(file_bytes) / 1024 / 1024:.1f} MB). "
            f"Maximum: {settings.redis_max_file_size_mb} MB."
        )

    # Validate the file can be loaded before storing
    fmt = filename.rsplit(".", 1)[-1].lower() if "." in filename else "sav"
    try:
        data = await run_in_executor(_load_data, file_bytes, fmt, filename)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to parse file: {e}")

    r = await _get_redis()
    if r is None:
        raise ToolError(
            "File sessions require Redis (REDIS_URL). "
            "Pass file_base64 directly to each tool as a fallback."
        )

    file_id = str(uuid_mod.uuid4())
    ttl = settings.spss_session_ttl_seconds
    try:
        import json as _json
        meta_info = _json.dumps({
            "filename": filename,
            "format": fmt,
            "n_cases": len(data.df),
            "n_variables": len(data.df.columns),
            "size_bytes": len(file_bytes),
        })
        await r.set(f"spss:file:{file_id}", file_bytes, ex=ttl)
        await r.set(f"spss:meta:{file_id}", meta_info.encode(), ex=ttl)
        await r.aclose()
    except Exception as e:
        try:
            await r.aclose()
        except Exception:
            pass
        raise ToolError(f"Failed to store file session: {e}")

    return {
        "file_id": file_id,
        "filename": filename,
        "format": fmt,
        "n_cases": len(data.df),
        "n_variables": len(data.df.columns),
        "size_bytes": len(file_bytes),
        "ttl_seconds": ttl,
        "message": (
            f"File uploaded. Use file_id='{file_id}' in subsequent tool calls. "
            f"Session expires after {ttl // 60} minutes of inactivity."
        ),
    }


# Tool 2: spss_get_metadata ──────────────────────────────────────────────────

async def get_spss_metadata(
    api_key: str,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Extract metadata from a data file.

    Returns variable names, labels, types, value labels, auto-detected question
    types (categorical/scale/dichotomy/open), suggested banners, detected groups
    (MRS, grid, scale), preset nets (T2B/B2B), and likely weight variables.

    Args:
        api_key:         Your API key (sk_test_... or sk_live_...).
        file_id:         File session ID from spss_upload_file (preferred).
        file_base64:     Base64-encoded file content (fallback if no file_id).
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    _auth(api_key)
    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        data = await run_in_executor(_load_data, file_bytes, fmt, filename)
        result = await run_in_executor(QuantiProEngine.extract_metadata, data)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to process file: {e}")

    return build_mcp_response(
        tool="spss_get_metadata",
        results=result,
        file_id=file_id,
        sample_size=result.get("n_cases", 0),
        format_detected=fmt,
        response_format=response_format,
    )


# Tool 3: spss_describe_variable ─────────────────────────────────────────────

async def get_variable_info(
    api_key: str,
    variable: str = "",
    variables: list[str] | None = None,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Get detailed information about specific variables in a data file.

    Returns name, label, data type, value labels, and auto-detected question
    type for each requested variable. Pass a single variable name or a list.

    Args:
        api_key:         Your API key.
        variable:        Single variable name (for spss_describe_variable).
        variables:       List of variable names (backwards compat).
        file_id:         File session ID from spss_upload_file.
        file_base64:     Base64-encoded file content.
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    _auth(api_key)
    # Accept either single variable or list
    var_list = variables or ([variable] if variable else [])
    if not var_list:
        raise ToolError("Provide 'variable' (single) or 'variables' (list).")

    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        data = await run_in_executor(_load_data, file_bytes, fmt, filename)
        result = await run_in_executor(QuantiProEngine.extract_metadata, data)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to process file: {e}")

    var_map = {v["name"]: v for v in result.get("variables", [])}
    missing = [v for v in var_list if v not in var_map]
    if missing:
        available = list(var_map.keys())[:30]
        raise ToolError(
            f"Variables not found: {missing}. "
            f"Available (first 30): {available}"
        )

    found = [var_map[v] for v in var_list]
    return build_mcp_response(
        tool="spss_describe_variable",
        results={"variables": found},
        file_id=file_id,
        variables_analyzed=var_list,
        sample_size=result.get("n_cases", 0),
        format_detected=fmt,
        response_format=response_format,
    )


# Tool 4: spss_analyze_frequencies ───────────────────────────────────────────

async def analyze_frequencies(
    api_key: str,
    variable: str = "",
    variables: list[str] | None = None,
    weight: str | None = None,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Run frequency analysis on one or more variables.

    Returns frequency tables with value labels, counts, percentages, valid
    percentages, mean, standard deviation, and median for each variable.
    Batch up to 50 variables in a single call.

    Args:
        api_key:         Your API key.
        variable:        Single variable name (backwards compat).
        variables:       List of variable names (batch mode, up to 50).
        weight:          Optional weight variable name.
        file_id:         File session ID from spss_upload_file.
        file_base64:     Base64-encoded file content.
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    _auth(api_key)
    var_list = variables or ([variable] if variable else [])
    if not var_list:
        raise ToolError("Provide 'variable' or 'variables'.")

    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        data = await run_in_executor(_load_data, file_bytes, fmt, filename)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to load file: {e}")

    results_list = []
    for var in var_list:
        try:
            freq_result = await run_in_executor(
                QuantiProEngine.frequency, data, var, weight
            )
            results_list.append(freq_result)
        except ValueError as e:
            raise ToolError(str(e))
        except Exception as e:
            raise ToolError(f"Frequency analysis failed for '{var}': {e}")

    combined = {"results": results_list}
    return build_mcp_response(
        tool="spss_analyze_frequencies",
        results=combined,
        file_id=file_id,
        variables_analyzed=var_list,
        sample_size=len(data.df),
        weighted=weight is not None,
        format_detected=fmt,
        response_format=response_format,
    )


# Tool 5: spss_analyze_crosstab ──────────────────────────────────────────────

async def analyze_crosstabs(
    api_key: str,
    row_variable: str = "",
    col_variable: str = "",
    row: str = "",
    col: str | list[str] = "",
    weight: str | None = None,
    significance_level: float = 0.95,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Run crosstab analysis between two variables with significance testing.

    Uses column proportion z-tests to assign significance letters (A, B, C, ...)
    to banner columns. A letter appears in a cell when this column's proportion
    is significantly higher than the lettered column's.

    Args:
        api_key:            Your API key.
        row / row_variable: Row (stub) variable name.
        col / col_variable: Column (banner) variable name(s).
        weight:             Optional weight variable name.
        significance_level: Confidence threshold (0.90, 0.95, or 0.99).
        file_id:            File session ID from spss_upload_file.
        file_base64:        Base64-encoded file content.
        filename:           Original filename (default: upload.sav).
        response_format:    'json' or 'markdown'.
    """
    _auth(api_key)
    # Accept both v1 (row_variable/col_variable) and v2 (row/col) param names
    actual_row = row or row_variable
    actual_col = col or col_variable
    if not actual_row or not actual_col:
        raise ToolError("Both row (stub) and col (banner) variables are required.")

    # v2 supports list of cols; for now process the first one
    if isinstance(actual_col, list):
        actual_col = actual_col[0] if actual_col else ""
    if not actual_col:
        raise ToolError("col variable is required.")

    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        data = await run_in_executor(_load_data, file_bytes, fmt, filename)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to load file: {e}")

    try:
        result = await run_in_executor(
            QuantiProEngine.crosstab_with_significance,
            data, actual_row, actual_col, weight, significance_level,
        )
    except ValueError as e:
        raise ToolError(str(e))
    except Exception as e:
        raise ToolError(f"Crosstab analysis failed: {e}")

    return build_mcp_response(
        tool="spss_analyze_crosstab",
        results=result,
        file_id=file_id,
        variables_analyzed=[actual_row, actual_col],
        sample_size=result.get("total_responses", len(data.df)),
        weighted=weight is not None,
        format_detected=fmt,
        response_format=response_format,
    )


# Tool 6: spss_export_data ───────────────────────────────────────────────────

async def export_data(
    api_key: str,
    target_format: str = "csv",
    format: str = "",
    apply_labels: bool = True,
    include_metadata_sheet: bool = True,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
) -> dict[str, Any]:
    """Export data file to another format.

    Converts the file to xlsx, csv, dta (Stata), or parquet.
    The converted file is returned as base64-encoded data in the `data_base64` field.

    Args:
        api_key:                Your API key.
        target_format:          Output format (v1 compat). "xlsx", "csv", "dta", or "parquet".
        format:                 Output format (v2 name). Same options.
        apply_labels:           Replace numeric codes with value labels (default True).
        include_metadata_sheet: Add a variable-labels sheet to Excel output (default True).
        file_id:                File session ID from spss_upload_file.
        file_base64:            Base64-encoded file content.
        filename:               Original filename (default: upload.sav).
    """
    _auth(api_key)
    actual_format = format or target_format
    valid_formats = {"xlsx", "csv", "dta", "parquet"}
    if actual_format not in valid_formats:
        raise ToolError(
            f"Invalid format '{actual_format}'. "
            f"Accepted: {', '.join(sorted(valid_formats))}"
        )

    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        data = await run_in_executor(_load_data, file_bytes, fmt, filename)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to load file: {e}")

    try:
        output_bytes, content_type, extension = await run_in_executor(
            FormatConverter.convert,
            data.df, data.meta, actual_format, apply_labels, include_metadata_sheet,
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


# Tool 7: spss_analyze_correlation (conditional: QUANTIPYMRX_AVAILABLE) ──────

async def analyze_correlation(
    api_key: str,
    variables: list[str] = [],
    method: str = "pearson",
    weight: str | None = None,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Run correlation analysis on selected variables.

    Returns a correlation matrix, p-values, and significant pairs (p < 0.05).
    Requires QuantipyMRX engine.

    Args:
        api_key:         Your API key (sk_test_... or sk_live_...).
        variables:       List of numeric variable names to correlate (minimum 2, max 20).
        method:          Correlation method — "pearson", "spearman", or "kendall".
        weight:          Optional weight variable name.
        file_id:         File session ID from spss_upload_file.
        file_base64:     Base64-encoded file content.
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    _auth(api_key)
    from routers.correlation import _run_correlation

    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        result = await run_in_executor(
            _run_correlation, file_bytes, filename,
            {"variables": variables, "method": method, "weight": weight},
        )
    except (ValueError, RuntimeError) as e:
        raise ToolError(str(e))
    except Exception as e:
        raise ToolError(f"Correlation analysis failed: {e}")

    return build_mcp_response(
        tool="spss_analyze_correlation",
        results=result,
        file_id=file_id,
        variables_analyzed=variables,
        sample_size=result.get("n_cases", 0),
        weighted=weight is not None,
        format_detected=fmt,
        response_format=response_format,
    )


# Tool 8: spss_analyze_anova (conditional: QUANTIPYMRX_AVAILABLE) ────────────

async def analyze_anova(
    api_key: str,
    dependent: str = "",
    factor: str = "",
    weight: str | None = None,
    post_hoc: bool = True,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Run one-way ANOVA with optional post-hoc tests.

    Tests whether the mean of `dependent` differs significantly across
    levels of `factor`. Optionally includes Tukey HSD post-hoc comparisons.
    Requires QuantipyMRX engine.

    Args:
        api_key:         Your API key (sk_test_... or sk_live_...).
        dependent:       Dependent (continuous) variable name.
        factor:          Factor (grouping) variable name.
        weight:          Optional weight variable name.
        post_hoc:        Run Tukey HSD post-hoc tests (default True).
        file_id:         File session ID from spss_upload_file.
        file_base64:     Base64-encoded file content.
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    _auth(api_key)
    from routers.anova import _run_anova

    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        result = await run_in_executor(
            _run_anova, file_bytes, filename,
            {"dependent": dependent, "factor": factor, "weight": weight, "post_hoc": post_hoc},
        )
    except (ValueError, RuntimeError) as e:
        raise ToolError(str(e))
    except Exception as e:
        raise ToolError(f"ANOVA analysis failed: {e}")

    return build_mcp_response(
        tool="spss_analyze_anova",
        results=result,
        file_id=file_id,
        variables_analyzed=[dependent, factor],
        sample_size=result.get("n_cases", len(result.get("group_ns", {}))),
        weighted=weight is not None,
        format_detected=fmt,
        response_format=response_format,
    )


# Tool 9: spss_analyze_gap (conditional: QUANTIPYMRX_AVAILABLE) ──────────────

async def analyze_gap(
    api_key: str,
    importance_vars: list[str] = [],
    performance_vars: list[str] = [],
    weight: str | None = None,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Run gap analysis (importance vs. performance).

    Compares paired importance and performance variables to identify
    priority areas (high importance, low performance) with quadrant classification.

    Args:
        api_key:           Your API key (sk_test_... or sk_live_...).
        importance_vars:   List of importance variable names.
        performance_vars:  List of performance variable names (same order).
        weight:            Optional weight variable name.
        file_id:           File session ID from spss_upload_file.
        file_base64:       Base64-encoded file content.
        filename:          Original filename (default: upload.sav).
        response_format:   'json' or 'markdown'.
    """
    _auth(api_key)
    from routers.gap_analysis import _run_gap_analysis

    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        result = await run_in_executor(
            _run_gap_analysis, file_bytes, filename,
            {"importance_vars": importance_vars, "performance_vars": performance_vars, "weight": weight},
        )
    except (ValueError, RuntimeError) as e:
        raise ToolError(str(e))
    except Exception as e:
        raise ToolError(f"Gap analysis failed: {e}")

    return build_mcp_response(
        tool="spss_analyze_gap",
        results=result,
        file_id=file_id,
        variables_analyzed=importance_vars + performance_vars,
        sample_size=result.get("n_cases", 0),
        weighted=weight is not None,
        format_detected=fmt,
        response_format=response_format,
    )


# Tool 10: spss_summarize_satisfaction (conditional: QUANTIPYMRX_AVAILABLE) ──

async def summarize_satisfaction(
    api_key: str,
    variables: list[str] = [],
    scale: str | None = None,
    weight: str | None = None,
    top_box: list[int] | None = None,
    bottom_box: list[int] | None = None,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Generate a satisfaction summary for selected variables.

    Computes mean, Top 2 Box, Bottom 2 Box, and distribution for each variable.
    Scale is auto-detected if not specified.

    Args:
        api_key:         Your API key (sk_test_... or sk_live_...).
        variables:       List of satisfaction variable names.
        scale:           Scale type — "5pt"/"1-5", "7pt"/"1-7", "10pt"/"1-10", or None for auto.
        weight:          Optional weight variable name.
        top_box:         Top Box values (e.g., [4, 5]).
        bottom_box:      Bottom Box values (e.g., [1, 2]).
        file_id:         File session ID from spss_upload_file.
        file_base64:     Base64-encoded file content.
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    _auth(api_key)
    from routers.satisfaction import _run_satisfaction_summary

    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        result = await run_in_executor(
            _run_satisfaction_summary, file_bytes, filename,
            {"variables": variables, "scale": scale, "weight": weight},
        )
    except (ValueError, RuntimeError) as e:
        raise ToolError(str(e))
    except Exception as e:
        raise ToolError(f"Satisfaction summary failed: {e}")

    return build_mcp_response(
        tool="spss_summarize_satisfaction",
        results=result,
        file_id=file_id,
        variables_analyzed=variables,
        sample_size=result.get("n_cases", 0),
        weighted=weight is not None,
        format_detected=fmt,
        response_format=response_format,
    )


# Tool 11: spss_create_tabulation ────────────────────────────────────────────

async def create_tabulation(
    api_key: str,
    banner: str = "",
    banners: list[str] | None = None,
    stubs: list[str] | None = None,
    significance_level: float = 0.95,
    weight: str | None = None,
    title: str = "",
    include_means: bool = False,
    include_total_column: bool = True,
    output_mode: str = "multi_sheet",
    nets: dict | None = None,
    mrs_groups: dict | None = None,
    grid_groups: dict | None = None,
    custom_groups: list[dict] | None = None,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Create a full tabulation Excel workbook with crosstabs and significance letters.

    Design decision (Option B): tables_summary is extracted from TabulationResult.sheets
    post-hoc rather than refactoring the tabulation builder. This keeps the builder
    stable while providing the JSON summary MCP clients need.

    Generates a professional .xlsx workbook:
    - Summary sheet: column legend (letter -> label) + stub index
    - One sheet per stub variable with column percentages + significance letters
    - Column bases (N), Top/Bottom 2 Box nets (if applicable)
    - Download URL (5-min TTL) if Redis is available, otherwise base64 fallback

    Args:
        api_key:              Your API key.
        banner:               Single banner variable (v1 compat).
        banners:              List of banner variables (v2, preferred).
        stubs:                List of stub variable names, or null for all.
        significance_level:   Confidence threshold (0.90, 0.95, 0.99).
        weight:               Optional weight variable name.
        title:                Report title in the Summary sheet.
        include_means:        Add means row with T-test significance.
        include_total_column: Include Total as first column.
        output_mode:          'multi_sheet' or 'single_sheet'.
        nets:                 Net definitions per stub.
        mrs_groups:           MRS group definitions.
        grid_groups:          Grid/battery summary definitions.
        custom_groups:        Custom break definitions.
        file_id:              File session ID from spss_upload_file.
        file_base64:          Base64-encoded file content.
        filename:             Original filename (default: upload.sav).
        response_format:      'json' or 'markdown'.
    """
    _auth(api_key)
    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        data = await run_in_executor(_load_data, file_bytes, fmt, filename)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Failed to load file: {e}")

    # Resolve banner(s)
    resolved_banners = banners or ([banner] if banner else [])
    if not resolved_banners:
        raise ToolError("At least one banner variable is required.")

    for b in resolved_banners:
        if b not in data.df.columns:
            available = list(data.df.columns[:20])
            raise ToolError(
                f"Banner variable '{b}' not found. "
                f"Available (first 20): {available}"
            )

    resolved_stubs = stubs if stubs else ["_all_"]
    if resolved_stubs != ["_all_"]:
        missing_stubs = [s for s in resolved_stubs if s not in data.df.columns]
        if missing_stubs:
            raise ToolError(f"Stub variables not found: {missing_stubs}")

    tab_spec = TabulateSpec(
        banners=resolved_banners,
        stubs=resolved_stubs,
        weight=weight,
        significance_level=significance_level,
        title=title,
        include_means=include_means,
        include_total_column=include_total_column,
        output_mode=output_mode,
        nets=nets or {},
        mrs_groups=mrs_groups or {},
        grid_groups=grid_groups or {},
        custom_groups=custom_groups,
    )
    try:
        result = await run_in_executor(build_tabulation, QuantiProEngine, data, tab_spec)
    except Exception as e:
        raise ToolError(f"Tabulation failed: {e}")

    # Extract tables_summary from sheets
    tables_summary = _extract_tables_summary(result.sheets)

    # Store for download
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
    dl_filename = f"tabulation_{base_name}.xlsx"
    _, download_url = await store_download(result.excel_bytes, dl_filename)

    tab_results = {
        "banners": resolved_banners,
        "total_stubs": result.total_stubs,
        "stubs_success": result.successful,
        "stubs_failed": result.failed,
        "tables_summary": tables_summary,
        "title": title,
        "sample_size": len(data.df),
    }

    envelope = build_mcp_response(
        tool="spss_create_tabulation",
        results=tab_results,
        file_id=file_id,
        variables_analyzed=resolved_stubs[:20],
        sample_size=len(data.df),
        weighted=weight is not None,
        format_detected=fmt,
        response_format=response_format,
        download_url=download_url or None,
        download_expires=300,
        download_filename=dl_filename,
    )

    # Include base64 fallback if no download URL
    if not download_url:
        envelope["data_base64"] = base64.b64encode(result.excel_bytes).decode()
    envelope["filename"] = dl_filename

    return envelope


# Tool 12: spss_auto_analyze ─────────────────────────────────────────────────

async def auto_analyze(
    api_key: str,
    max_banners: int = 3,
    output_mode: str = "multi_sheet",
    significance_level: float = 0.95,
    include_means: bool = True,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Zero-config automatic analysis of a data file.

    Automatically selects banners, stubs, and nets, then produces a full
    tabulation Excel workbook. Returns a download URL and a summary of
    what was analyzed.

    Args:
        api_key:            Your API key (sk_test_... or sk_live_...).
        max_banners:        Maximum number of banner variables to use (default 3).
        output_mode:        Output mode — "multi_sheet" or "single_sheet".
        significance_level: Confidence threshold (0.90, 0.95, 0.99).
        include_means:      Include means with T-test (default True).
        file_id:            File session ID from spss_upload_file.
        file_base64:        Base64-encoded file content.
        filename:           Original filename (default: upload.sav).
        response_format:    'json' or 'markdown'.
    """
    _auth(api_key)
    from routers.auto_analyze import _run_auto_analyze

    file_bytes, fmt = await _resolve_file(file_id, file_base64, filename)
    try:
        result = await run_in_executor(
            _run_auto_analyze, file_bytes, filename,
            {
                "max_banners": max_banners,
                "output_mode": output_mode,
                "significance_level": significance_level,
                "include_means": include_means,
            },
        )
    except (ValueError, RuntimeError) as e:
        raise ToolError(str(e))
    except Exception as e:
        raise ToolError(f"Auto-analyze failed: {e}")

    # Store for download
    dl_filename = result.get("filename", f"auto_analyze_{filename.rsplit('.', 1)[0]}.xlsx")
    _, download_url = await store_download(result["excel_bytes"], dl_filename)

    summary = result["summary"]
    auto_results = {
        "banners": summary.get("banners", []),
        "banner_labels": summary.get("banner_labels", []),
        "total_stubs": summary.get("total_stubs", 0),
        "stubs_success": summary.get("stubs_success", 0),
        "stubs_failed": summary.get("stubs_failed", 0),
        "mrs_groups": summary.get("mrs_groups", 0),
        "grid_groups": summary.get("grid_groups", 0),
        "nets_applied": summary.get("nets_applied", 0),
        "title": f"Auto-Analysis: {filename}",
        "sample_size": 0,
    }

    envelope = build_mcp_response(
        tool="spss_auto_analyze",
        results=auto_results,
        file_id=file_id,
        format_detected=fmt,
        response_format=response_format,
        download_url=download_url or None,
        download_expires=300,
        download_filename=dl_filename,
    )

    # Include base64 fallback if no download URL
    if not download_url:
        envelope["data_base64"] = base64.b64encode(result["excel_bytes"]).decode()
    envelope["filename"] = dl_filename

    return envelope


# Tool 13: spss_list_tools ───────────────────────────────────────────────────

async def list_files(api_key: str) -> dict[str, Any]:
    """Return API capabilities and connection info for the authenticated user.

    Validates your API key and returns your plan info, available tools,
    and file session status.

    Args:
        api_key: Your API key.
    """
    key_config = _auth(api_key)
    r = await _get_redis()
    redis_available = r is not None
    if r:
        try:
            await r.aclose()
        except Exception:
            pass

    return {
        "server": "SPSS InsightGenius MCP Server v2",
        "key_name": key_config.name,
        "plan": key_config.plan,
        "scopes": key_config.scopes,
        "file_sessions_enabled": redis_available,
        "session_ttl_seconds": get_settings().spss_session_ttl_seconds,
        "note": (
            "Upload files once with spss_upload_file to get a reusable file_id. "
            "Sessions last 30 minutes (sliding). Or pass file_base64 directly."
        ) if redis_available else (
            "File sessions unavailable (no Redis). "
            "Pass file_base64 directly in each tool call."
        ),
        "available_tools": [
            {"name": "spss_upload_file", "description": "Upload a file and get a reusable file_id"},
            {"name": "spss_get_metadata", "description": "Extract variable metadata, banners, groups, nets"},
            {"name": "spss_describe_variable", "description": "Get detailed profile for specific variables"},
            {"name": "spss_analyze_frequencies", "description": "Frequency tables (batch up to 50 variables)"},
            {"name": "spss_analyze_crosstab", "description": "Crosstab with significance letters (A/B/C)"},
            {"name": "spss_export_data", "description": "Convert to xlsx / csv / dta / parquet"},
            {"name": "spss_create_tabulation", "description": "Full tabulation Excel workbook"},
            {"name": "spss_auto_analyze", "description": "Zero-config: auto-detect everything, produce Excel"},
            {"name": "spss_list_tools", "description": "This tool — list capabilities and plan info"},
            *([
                {"name": "spss_analyze_correlation", "description": "Correlation matrix with p-values"},
                {"name": "spss_analyze_anova", "description": "One-way ANOVA with Tukey HSD post-hoc"},
                {"name": "spss_analyze_gap", "description": "Importance vs. performance gap analysis"},
                {"name": "spss_summarize_satisfaction", "description": "T2B/B2B/Mean satisfaction summary"},
            ] if QUANTIPYMRX_AVAILABLE else []),
        ],
    }


# ── MCP Tool Registration ────────────────────────────────────────────────────

# Always-available tools (9)
_ALWAYS_TOOLS = [
    ("spss_upload_file", spss_upload_file),
    ("spss_get_metadata", get_spss_metadata),
    ("spss_describe_variable", get_variable_info),
    ("spss_analyze_frequencies", analyze_frequencies),
    ("spss_analyze_crosstab", analyze_crosstabs),
    ("spss_export_data", export_data),
    ("spss_create_tabulation", create_tabulation),
    ("spss_auto_analyze", auto_analyze),
    ("spss_list_tools", list_files),
]

# Conditional tools (require QuantipyMRX)
_CONDITIONAL_TOOLS = [
    ("spss_analyze_correlation", analyze_correlation),
    ("spss_analyze_anova", analyze_anova),
    ("spss_analyze_gap", analyze_gap),
    ("spss_summarize_satisfaction", summarize_satisfaction),
]

for _name, _fn in _ALWAYS_TOOLS:
    mcp.tool(name=_name)(_fn)

if QUANTIPYMRX_AVAILABLE:
    for _name, _fn in _CONDITIONAL_TOOLS:
        mcp.tool(name=_name)(_fn)
    logger.info("MCP: Registered all 13 tools (QuantipyMRX available)")
else:
    for _name, _fn in _CONDITIONAL_TOOLS:
        logger.warning(
            "MCP: Tool '%s' NOT registered — QuantipyMRX not available", _name
        )
    logger.info("MCP: Registered 9 of 13 tools (QuantipyMRX not available)")


# ── Redis-backed SSE transport ─────────────────────────────────────────────────
#
# Railway with numReplicas > 1: the SSE GET and the POST /messages/ may land on
# different replicas. Sessions (MemoryObjectSendStream) are in-memory and can't
# cross processes, so we relay via Redis pub/sub:
#
#   POST on Replica B (session not found locally):
#     -> publish body to Redis `mcp:msg:{session_id}`
#     -> return 202 Accepted
#
#   Replica A (owns the session, subscribed to `mcp:msg:*`):
#     -> receives pub/sub message
#     -> writes JSON-RPC body to local stream
#     -> FastMCP processes it and responds via the SSE connection
#
# If REDIS_URL is not set, the relay is disabled (single-replica mode).

# Module-level SSE transport — shared between the ASGI app routes and the relay.
# endpoint is the path the client POSTs to (relative to this app's mount point).
_sse_transport = SseServerTransport("/messages/")

# Persistent Redis client for publishing (connection-pooled).
_redis_pub: aioredis.Redis | None = None

# Background task handle for the pub/sub subscriber loop.
_redis_subscriber_task: asyncio.Task | None = None


async def _redis_subscriber_loop() -> None:
    """Subscribe to `mcp:msg:*` and forward messages to local SSE sessions.

    Runs as a background task (started by start_redis_relay).
    Retries with exponential back-off on connection failure.
    """
    settings = get_settings()
    redis_url = settings.redis_url
    retry_delay = 1.0

    while True:
        try:
            async with aioredis.from_url(redis_url, decode_responses=False) as sub_redis:
                pubsub = sub_redis.pubsub()
                await pubsub.psubscribe("mcp:msg:*")
                logger.info("MCP Redis relay: subscribed to mcp:msg:*")
                retry_delay = 1.0  # reset on successful connect

                async for message in pubsub.listen():
                    if message["type"] != "pmessage":
                        continue

                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()

                    # channel format: mcp:msg:{session_id_hex}
                    session_id_hex = channel.split(":")[-1]
                    try:
                        session_id = UUID(hex=session_id_hex)
                    except ValueError:
                        continue

                    writer = _sse_transport._read_stream_writers.get(session_id)
                    if not writer:
                        continue  # session lives on another replica — ignore

                    body = message["data"]
                    try:
                        msg = types.JSONRPCMessage.model_validate_json(body)
                        await writer.send(SessionMessage(msg))
                        logger.debug(
                            "MCP Redis relay: forwarded message for session %.8s",
                            session_id_hex,
                        )
                    except Exception as exc:
                        logger.warning(
                            "MCP Redis relay: failed to deliver message for session %.8s: %s",
                            session_id_hex, exc,
                        )

        except asyncio.CancelledError:
            logger.info("MCP Redis relay: subscriber stopped")
            return
        except Exception as exc:
            logger.warning(
                "MCP Redis relay: connection error (%s) — retrying in %.1fs",
                exc, retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


async def start_redis_relay() -> None:
    """Start the Redis pub/sub relay. Called from the FastAPI app lifespan."""
    global _redis_pub, _redis_subscriber_task
    settings = get_settings()
    if not settings.redis_url:
        logger.warning(
            "MCP Redis relay: REDIS_URL not set — POST /mcp/messages/ will return 404 "
            "when Railway routes SSE and POST to different replicas (numReplicas > 1). "
            "Set REDIS_URL to enable cross-replica session routing."
        )
        return

    _redis_pub = aioredis.from_url(settings.redis_url, decode_responses=False)
    _redis_subscriber_task = asyncio.create_task(_redis_subscriber_loop())
    logger.info("MCP Redis relay started (REDIS_URL configured)")


async def stop_redis_relay() -> None:
    """Stop the Redis pub/sub relay. Called from the FastAPI app lifespan."""
    global _redis_pub, _redis_subscriber_task
    if _redis_subscriber_task:
        _redis_subscriber_task.cancel()
        try:
            await _redis_subscriber_task
        except asyncio.CancelledError:
            pass
        _redis_subscriber_task = None
    if _redis_pub:
        await _redis_pub.aclose()
        _redis_pub = None


async def _handle_post_with_redis(scope: Any, receive: Any, send: Any) -> None:
    """POST /messages/ handler with Redis relay for cross-replica session routing.

    If the session_id from the query string is owned by this replica, the
    message is handled locally (standard FastMCP path).

    If the session is on another replica, the raw JSON body is published to
    `mcp:msg:{session_id}` in Redis so the owning replica can deliver it.
    """
    request = Request(scope, receive)
    session_id_param = request.query_params.get("session_id")

    if session_id_param:
        try:
            session_id = UUID(hex=session_id_param)
        except ValueError:
            # Invalid UUID — let the transport return 400
            await _sse_transport.handle_post_message(scope, receive, send)
            return

        if session_id not in _sse_transport._read_stream_writers:
            if _redis_pub is not None:
                body = await request.body()
                try:
                    subscriber_count = await _redis_pub.publish(
                        f"mcp:msg:{session_id_param}", body
                    )
                    if subscriber_count == 0:
                        logger.warning(
                            "MCP Redis relay: no subscriber for session %.8s — "
                            "session may have expired",
                            session_id_param,
                        )
                        response = Response("Could not find session", status_code=404)
                    else:
                        response = Response("Accepted", status_code=202)
                    await response(scope, receive, send)
                    return
                except Exception as exc:
                    logger.error("MCP Redis relay: publish failed: %s", exc)
                    response = Response("Service unavailable", status_code=503)
                    await response(scope, receive, send)
                    return
            # Redis not configured — fall through to local handler (returns 404)

    await _sse_transport.handle_post_message(scope, receive, send)


# ── ASGI app factory ──────────────────────────────────────────────────────────

def get_mcp_asgi_app():
    """Return the MCP SSE ASGI app for mounting in the main FastAPI app.

    SSE endpoint:  GET  /mcp/sse
    Post endpoint: POST /mcp/messages/

    Sessions are relayed across Railway replicas via Redis pub/sub when
    REDIS_URL is set (see start_redis_relay / stop_redis_relay).
    """

    async def handle_sse(scope: Any, receive: Any, send: Any) -> Response:
        async with _sse_transport.connect_sse(scope, receive, send) as streams:
            await mcp._mcp_server.run(
                streams[0],
                streams[1],
                mcp._mcp_server.create_initialization_options(),
            )
        return Response()

    async def sse_endpoint(request: Request) -> Response:
        return await handle_sse(request.scope, request.receive, request._send)  # type: ignore[reportPrivateUsage]

    return Starlette(routes=[
        Route("/sse", endpoint=sse_endpoint, methods=["GET"]),
        Mount("/messages/", app=_handle_post_with_redis),
    ])
