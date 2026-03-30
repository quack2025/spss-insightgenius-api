"""MCP tools: file upload, metadata extraction, variable description."""

import json
from typing import Any

from fastmcp.exceptions import ToolError

from config import get_settings
from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine
from services.response_formatter import build_mcp_response

from mcp_server.auth import _auth_async, _make_error
from mcp_server.file_session import _get_redis, _resolve_file, _load_data


async def spss_upload_file(
    file_id: str | None = None,
    api_key: str = "",
) -> dict[str, Any]:
    """Get a file_id for analysis. Users upload files via the web UI, not through this tool.

    IMPORTANT — How file upload works:
    1. Ask the user to go to https://spss.insightgenius.io/upload
    2. They drag & drop their file there and get a file_id (e.g., "abc123")
    3. They paste the file_id back in chat
    4. You use that file_id in all subsequent tool calls (spss_get_metadata, spss_analyze_frequencies, etc.)

    DO NOT attempt to encode files as base64. DO NOT use file_base64. Always use the upload URL.
    If the user already has a file_id, just pass it to validate the session.

    Sessions last 30 minutes (sliding TTL — refreshed on each use).

    Authentication: OAuth (Claude.ai) = no api_key needed. Claude Desktop = pass api_key.

    Args:
        file_id:  File ID from https://spss.insightgenius.io/upload. Ask user if you don't have one.
        api_key:  API key (sk_test_... or sk_live_...). Optional if connected via OAuth.
    """
    await _auth_async(api_key)

    # If file_id provided, validate it exists and return session info
    if file_id:
        r = await _get_redis()
        if r is None:
            raise ToolError("File sessions require Redis (REDIS_URL).")
        try:
            meta_raw = await r.get(f"spss:meta:{file_id}")
            await r.aclose()
        except Exception as e:
            try:
                await r.aclose()
            except Exception:
                pass
            raise ToolError(f"Redis error: {e}")

        if not meta_raw:
            raise ToolError(f"file_id '{file_id}' not found or expired.")
        meta = json.loads(meta_raw)
        return {
            "file_id": file_id,
            "filename": meta.get("filename", "unknown"),
            "format_detected": meta.get("format", "sav"),
            "n_cases": meta.get("n_cases", 0),
            "n_variables": meta.get("n_variables", 0),
            "size_bytes": meta.get("size_bytes", 0),
            "message": f"File session active. Use file_id='{file_id}' in subsequent tool calls.",
        }

    # No file_id provided — direct user to upload page
    return {
        "file_id": None,
        "upload_url": "https://spss.insightgenius.io/upload",
        "message": (
            "To analyze a file, the user needs to upload it first:\n"
            "1. Go to https://spss.insightgenius.io/upload\n"
            "2. Drag & drop the file (.sav, .csv, or .xlsx)\n"
            "3. Copy the file_id shown after upload\n"
            "4. Paste it back here\n\n"
            "Then call any analysis tool with that file_id."
        ),
    }


async def get_spss_metadata(
    api_key: str = "",
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Get comprehensive metadata for an uploaded data file: variable names, types, labels, value labels, AI-detected banner variables, MRS groups, grid/battery variables, and suggested nets. Returns structured survey intelligence that goes far beyond what pandas.describe() provides.

    Authentication: If connected via OAuth (Claude.ai connector), no api_key needed. If using Claude Desktop or direct API, pass api_key (sk_test_... or sk_live_...).

    Requires a file_id from a previous spss_upload_file call, or pass file_base64 directly.

    Args:
        api_key:         Your API key (sk_test_... or sk_live_...). REQUIRED.
        file_id:         File session ID from spss_upload_file (preferred).
        file_base64:     Base64-encoded file content (fallback if no file_id).
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    await _auth_async(api_key)
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


async def get_variable_info(
    api_key: str = "",
    variable: str = "",
    variables: list[str] | None = None,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Deep profile of specific variables: distribution, labels, missing values, statistics. Use this to understand a specific question/variable before running cross-tabulations.

    Authentication: If connected via OAuth (Claude.ai connector), no api_key needed. If using Claude Desktop or direct API, pass api_key (sk_test_... or sk_live_...).

    Requires a file_id from a previous spss_upload_file call, or pass file_base64 directly.

    Args:
        api_key:         Your API key (sk_test_... or sk_live_...). REQUIRED.
        variable:        Single variable name.
        variables:       List of variable names.
        file_id:         File session ID from spss_upload_file.
        file_base64:     Base64-encoded file content.
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    await _auth_async(api_key)
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
