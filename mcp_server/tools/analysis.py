"""MCP tools: frequency analysis and cross-tabulation."""

import json
from typing import Any

from fastmcp.exceptions import ToolError

from middleware.processing import run_in_executor
from services.quantipy_engine import QuantiProEngine
from services.response_formatter import build_mcp_response

from mcp_server.auth import _auth_async, _make_error
from mcp_server.file_session import _resolve_file, _load_data


def _validate_variables(var_list: list[str], df_columns) -> None:
    """Validate that all variables exist in the dataframe."""
    for var in var_list:
        if var not in df_columns:
            available = sorted(list(df_columns)[:30])
            raise ToolError(json.dumps(_make_error(
                "variable_not_found",
                f"Variable '{var}' not found. Available: {available}",
                "Check variable names with spss_get_metadata first.",
            )))


async def analyze_frequencies(
    api_key: str = "",
    variable: str = "",
    variables: list[str] | None = None,
    weight: str | None = None,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Frequency tables with percentages, counts, mean, standard deviation, and median. Supports batch analysis of up to 50 variables in a single call. Returns professional market research output with content_blocks ready for presentations.

    Authentication: If connected via OAuth (Claude.ai connector), no api_key needed. If using Claude Desktop or direct API, pass api_key (sk_test_... or sk_live_...).

    Requires a file_id from a previous spss_upload_file call, or pass file_base64 directly.

    Args:
        api_key:         Your API key (sk_test_... or sk_live_...). REQUIRED.
        variable:        Single variable name.
        variables:       List of variable names (batch mode, up to 50).
        weight:          Optional weight variable name.
        file_id:         File session ID from spss_upload_file.
        file_base64:     Base64-encoded file content.
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    await _auth_async(api_key)
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

    # Validate variables exist
    _validate_variables(var_list, data.df.columns)

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


async def analyze_crosstabs(
    api_key: str = "",
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
    """Cross-tabulation with column proportion z-test significance testing at 90/95/99% confidence. Returns letter notation (A/B/C) showing which columns are significantly different — the industry standard for market research reporting. Includes chi-square test, column percentages, and optional means.

    This is a specialized statistical analysis that Python's pandas CANNOT replicate — it requires the exact significance testing methodology used in professional market research (column proportion z-test with Bonferroni correction and letter notation).

    Authentication: If connected via OAuth (Claude.ai connector), no api_key needed. If using Claude Desktop or direct API, pass api_key (sk_test_... or sk_live_...).

    Args:
        api_key:            Your API key (sk_test_... or sk_live_...). REQUIRED.
        row / row_variable: Row (stub) variable name.
        col / col_variable: Column (banner) variable name(s).
        weight:             Optional weight variable name.
        significance_level: Confidence threshold (0.90, 0.95, or 0.99).
        file_id:            File session ID from spss_upload_file.
        file_base64:        Base64-encoded file content.
        filename:           Original filename (default: upload.sav).
        response_format:    'json' or 'markdown'.
    """
    await _auth_async(api_key)
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

    # Validate variables exist
    _validate_variables([actual_row, actual_col], data.df.columns)

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
