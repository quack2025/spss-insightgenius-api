"""Backwards compatibility — imports from mcp_server package.

All MCP server code has been moved to the `mcp_server/` package.
This module re-exports the public API so existing imports continue to work.
"""

from mcp_server import (  # noqa: F401
    mcp,
    get_mcp_asgi_app,
    start_redis_relay,
    stop_redis_relay,
    # Tool functions (used by tests)
    spss_get_server_info,
    spss_get_started,
    spss_upload_file,
    get_spss_metadata,
    get_variable_info,
    analyze_frequencies,
    analyze_crosstabs,
    analyze_correlation,
    analyze_anova,
    analyze_gap,
    summarize_satisfaction,
    create_tabulation,
    auto_analyze,
    export_data,
    list_files,
    # Helpers used by routers/file_upload.py
    _load_data,
    _get_redis,
)
