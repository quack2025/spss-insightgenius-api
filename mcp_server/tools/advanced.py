"""MCP tools: correlation, ANOVA, gap analysis, satisfaction summary.

These tools are conditionally registered — they require QuantipyMRX.
"""

from typing import Any

from fastmcp.exceptions import ToolError

from middleware.processing import run_in_executor
from services.response_formatter import build_mcp_response

from mcp_server.auth import _auth_async
from mcp_server.file_session import _resolve_file


async def analyze_correlation(
    api_key: str = "",
    variables: list[str] = [],
    method: str = "pearson",
    weight: str | None = None,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Correlation matrix with Pearson, Spearman, or Kendall methods. Returns correlation coefficients with p-values and significance flags.

    Authentication: If connected via OAuth (Claude.ai connector), no api_key needed. If using Claude Desktop or direct API, pass api_key (sk_test_... or sk_live_...).

    Requires a file_id from a previous spss_upload_file call, or pass file_base64 directly.

    Args:
        api_key:         Your API key (sk_test_... or sk_live_...). REQUIRED.
        variables:       List of numeric variable names to correlate (minimum 2, max 20).
        method:          Correlation method — "pearson", "spearman", or "kendall".
        weight:          Optional weight variable name.
        file_id:         File session ID from spss_upload_file.
        file_base64:     Base64-encoded file content.
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    await _auth_async(api_key)
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


async def analyze_anova(
    api_key: str = "",
    dependent: str = "",
    factor: str = "",
    weight: str | None = None,
    post_hoc: bool = True,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """One-way ANOVA with Tukey HSD post-hoc pairwise comparisons. Identifies which groups differ significantly from each other.

    Authentication: If connected via OAuth (Claude.ai connector), no api_key needed. If using Claude Desktop or direct API, pass api_key (sk_test_... or sk_live_...).

    Requires a file_id from a previous spss_upload_file call, or pass file_base64 directly.

    Args:
        api_key:         Your API key (sk_test_... or sk_live_...). REQUIRED.
        dependent:       Dependent (continuous) variable name.
        factor:          Factor (grouping) variable name.
        weight:          Optional weight variable name.
        post_hoc:        Run Tukey HSD post-hoc tests (default True).
        file_id:         File session ID from spss_upload_file.
        file_base64:     Base64-encoded file content.
        filename:        Original filename (default: upload.sav).
        response_format: 'json' or 'markdown'.
    """
    await _auth_async(api_key)
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


async def analyze_gap(
    api_key: str = "",
    importance_vars: list[str] = [],
    performance_vars: list[str] = [],
    weight: str | None = None,
    file_base64: str | None = None,
    filename: str = "upload.sav",
    file_id: str | None = None,
    response_format: str = "json",
) -> dict[str, Any]:
    """Importance-Performance gap analysis with quadrant classification (Concentrate Here, Keep Up, Low Priority, Possible Overkill). Standard framework for prioritizing improvements in customer experience research.

    Authentication: If connected via OAuth (Claude.ai connector), no api_key needed. If using Claude Desktop or direct API, pass api_key (sk_test_... or sk_live_...).

    Requires a file_id from a previous spss_upload_file call, or pass file_base64 directly.

    Args:
        api_key:           Your API key (sk_test_... or sk_live_...). REQUIRED.
        importance_vars:   List of importance variable names.
        performance_vars:  List of performance variable names (same order as importance).
        weight:            Optional weight variable name.
        file_id:           File session ID from spss_upload_file.
        file_base64:       Base64-encoded file content.
        filename:          Original filename (default: upload.sav).
        response_format:   'json' or 'markdown'.
    """
    await _auth_async(api_key)
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


async def summarize_satisfaction(
    api_key: str = "",
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
    """Compact satisfaction summary: Top 2 Box (T2B), Bottom 2 Box (B2B), and Mean for scale variables. The standard KPI format used in market research reporting.

    Authentication: If connected via OAuth (Claude.ai connector), no api_key needed. If using Claude Desktop or direct API, pass api_key (sk_test_... or sk_live_...).

    Requires a file_id from a previous spss_upload_file call, or pass file_base64 directly.

    Args:
        api_key:         Your API key (sk_test_... or sk_live_...). REQUIRED.
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
    await _auth_async(api_key)
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
