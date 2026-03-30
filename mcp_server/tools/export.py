"""MCP tools: data export."""

import base64
from typing import Any

from fastmcp.exceptions import ToolError

from middleware.processing import run_in_executor
from services.converter import FormatConverter

from mcp_server.auth import _auth_async
from mcp_server.file_session import _resolve_file, _load_data


async def export_data(
    api_key: str = "",
    target_format: str = "csv",
    format: str = "",
    apply_labels: bool = True,
    include_metadata_sheet: bool = True,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
) -> dict[str, Any]:
    """Convert uploaded data file to xlsx, csv, dta, or parquet format. Supports applying value labels and including a metadata sheet.

    Authentication: If connected via OAuth (Claude.ai connector), no api_key needed. If using Claude Desktop or direct API, pass api_key (sk_test_... or sk_live_...).

    Requires a file_id from a previous spss_upload_file call, or pass file_base64 directly.

    Args:
        api_key:                Your API key (sk_test_... or sk_live_...). REQUIRED.
        target_format:          Output format. "xlsx", "csv", "dta", or "parquet".
        format:                 Output format (alternative name). Same options.
        apply_labels:           Replace numeric codes with value labels (default True).
        include_metadata_sheet: Add a variable-labels sheet to Excel output (default True).
        file_id:                File session ID from spss_upload_file.
        file_base64:            Base64-encoded file content.
        filename:               Original filename (default: upload.sav).
    """
    await _auth_async(api_key)
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
