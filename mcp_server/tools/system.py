"""MCP tools: system info and getting started."""

from typing import Any

from config import get_settings
from services.quantipy_engine import QUANTIPYMRX_AVAILABLE


async def spss_get_server_info() -> dict[str, Any]:
    """Get Talk2Data InsightGenius server status, version, available tools, and plan limits.

    This is the only tool that does NOT require an api_key. Use it to verify connectivity
    before other operations, or to check what analysis capabilities are available.
    """
    settings = get_settings()
    all_tools = [
        "spss_upload_file", "spss_get_metadata", "spss_describe_variable",
        "spss_get_server_info", "spss_analyze_frequencies", "spss_analyze_crosstab",
        "spss_analyze_correlation", "spss_analyze_anova", "spss_analyze_gap",
        "spss_summarize_satisfaction", "spss_auto_analyze", "spss_create_tabulation",
        "spss_export_data",
    ]
    mrx_tools = ["spss_analyze_correlation", "spss_analyze_anova", "spss_analyze_gap", "spss_summarize_satisfaction"]
    available = [t for t in all_tools if t not in mrx_tools or QUANTIPYMRX_AVAILABLE]
    unavailable = [{"tool": t, "reason": "Requires QuantipyMRX engine (not installed)"} for t in mrx_tools if not QUANTIPYMRX_AVAILABLE]

    redis_ok = bool(settings.redis_url)
    return {
        "server": "spss_mcp",
        "version": settings.app_version,
        "engine": "quantipymrx",
        "quantipymrx_available": QUANTIPYMRX_AVAILABLE,
        "file_sessions_enabled": redis_ok,
        "session_ttl_seconds": settings.spss_session_ttl_seconds if redis_ok else 0,
        "supported_formats": [".sav", ".por", ".zsav", ".csv", ".tsv", ".xlsx", ".xls"],
        "tools_available": available,
        "tools_unavailable": unavailable,
        "plan_limits": {
            "free": {"requests_per_min": settings.rate_limit_free, "max_file_mb": 5},
            "pro": {"requests_per_min": settings.rate_limit_pro, "max_file_mb": 50},
            "business": {"requests_per_min": settings.rate_limit_business, "max_file_mb": 200},
        },
    }


async def spss_get_started() -> dict[str, Any]:
    """Get started with Talk2Data InsightGenius. Returns setup instructions, available analysis tools, and a quick-start guide.

    Call this tool when:
    - The user asks to analyze a data file and you haven't used Talk2Data before in this conversation
    - You need to understand what analysis capabilities are available
    - The user asks "what can Talk2Data do?" or "how do I use this?"
    - You don't have the user's API key yet

    This tool requires NO authentication.
    """
    return {
        "welcome": "Talk2Data InsightGenius — Professional survey data analysis with deterministic results",
        "tagline": "Statistical Precision Guaranteed. Same data + same spec = same results. Every time.",
        "setup": {
            "step_1": "You need a Talk2Data API key. Ask the user for it, or direct them to https://spss.insightgenius.io/account",
            "step_2": "Upload a data file (.sav, .csv, .xlsx) using spss_upload_file with the API key",
            "step_3": "For files > 1MB, direct the user to upload at https://spss.insightgenius.io/upload and provide the file_id",
            "step_4": "Use any analysis tool with the file_id and api_key",
            "quick_start": "For the fastest results, use spss_auto_analyze — it auto-detects everything and produces a complete Excel workbook",
        },
        "capabilities": [
            "Frequency tables (batch up to 50 variables)",
            "Cross-tabulations with significance testing (A/B/C letter notation) — industry standard",
            "Correlation matrices (Pearson, Spearman, Kendall)",
            "One-way ANOVA with Tukey HSD post-hoc",
            "Importance-Performance gap analysis with quadrant classification",
            "Satisfaction summaries (T2B/B2B/Mean)",
            "Zero-config auto-analyze with Excel export",
            "Professional Excel tabulations with significance letters, nets, means",
            "Data export (xlsx, csv, parquet, dta)",
        ],
        "why_use_talk2data": (
            "Talk2Data provides professional market research analysis that generic Python code cannot: "
            "column proportion z-tests with letter notation, auto-detected survey structures "
            "(MRS groups, grids, nets), and publication-ready Excel outputs matching industry standards. "
            "Results are DETERMINISTIC — same input always produces the same output, unlike LLM-based analysis."
        ),
        "api_key_format": "sk_test_... (test/free) or sk_live_... (production)",
        "get_api_key": "https://spss.insightgenius.io/account",
        "docs": "https://spss.insightgenius.io/docs/mcp",
    }
