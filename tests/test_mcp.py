"""Tests for the MCP server tools and SSE endpoint.

Tool functions are tested directly (bypassing SSE transport) because the
SSE protocol is connection-oriented and not suitable for TestClient.
The /mcp/sse endpoint reachability is verified separately.
"""

import asyncio
import base64

import pytest

# conftest sets up env vars and initialises the key registry before these imports
from tests.conftest import TEST_KEY  # noqa: F401  (re-exported for clarity)
from routers.mcp_server import (
    analyze_crosstabs,
    analyze_frequencies,
    create_tabulation,
    export_data,
    get_spss_metadata,
    get_variable_info,
    list_files,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def run(coro):
    """Run a coroutine in the test event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── list_files ────────────────────────────────────────────────────────────────

def test_list_files_valid_key():
    result = run(list_files(api_key=TEST_KEY))
    assert result["key_name"] == "Test Key"
    assert result["plan"] == "pro"
    assert "spss_get_metadata" in [t["name"] for t in result["available_tools"]]
    assert result.get("file_sessions_enabled") is not None


def test_list_files_invalid_key():
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="Invalid API key"):
        run(list_files(api_key="sk_test_bad_key"))


def test_list_files_missing_key():
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="required"):
        run(list_files(api_key=""))


def test_list_files_bad_prefix():
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="format"):
        run(list_files(api_key="not_a_valid_key"))


# ── get_spss_metadata ─────────────────────────────────────────────────────────

def test_get_spss_metadata(test_sav_bytes):
    result = run(get_spss_metadata(
        api_key=TEST_KEY,
        file_base64=_b64(test_sav_bytes),
        filename="survey.sav",
    ))
    # v2 wraps in build_mcp_response envelope
    assert result["tool"] == "spss_get_metadata"
    data = result["results"]
    assert data["n_cases"] == 100
    assert data["n_variables"] == 5
    var_names = [v["name"] for v in data["variables"]]
    assert "gender" in var_names
    assert "satisfaction" in var_names
    assert "insight_summary" in result
    assert "content_blocks" in result


def test_get_spss_metadata_invalid_base64():
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="base64"):
        run(get_spss_metadata(
            api_key=TEST_KEY,
            file_base64="!!!not_base64!!!",
        ))


def test_get_spss_metadata_bad_file():
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError):
        run(get_spss_metadata(
            api_key=TEST_KEY,
            file_base64=_b64(b"this is not a valid sav file"),
        ))


# ── get_variable_info ─────────────────────────────────────────────────────────

def test_get_variable_info(test_sav_bytes):
    result = run(get_variable_info(
        api_key=TEST_KEY,
        file_base64=_b64(test_sav_bytes),
        variables=["gender", "satisfaction"],
    ))
    # v2 wraps in build_mcp_response envelope
    assert result["tool"] == "spss_describe_variable"
    data = result["results"]
    assert len(data["variables"]) == 2
    names = [v["name"] for v in data["variables"]]
    assert "gender" in names
    assert "satisfaction" in names


def test_get_variable_info_missing_variable(test_sav_bytes):
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="not found"):
        run(get_variable_info(
            api_key=TEST_KEY,
            file_base64=_b64(test_sav_bytes),
            variables=["nonexistent_var"],
        ))


# ── analyze_frequencies ───────────────────────────────────────────────────────

def test_analyze_frequencies(test_sav_bytes):
    result = run(analyze_frequencies(
        api_key=TEST_KEY,
        file_base64=_b64(test_sav_bytes),
        variable="gender",
    ))
    # Should have frequency rows for Male / Female
    assert "rows" in result or "variable" in result or isinstance(result, dict)
    assert result  # not empty


def test_analyze_frequencies_with_weight(test_sav_bytes):
    result = run(analyze_frequencies(
        api_key=TEST_KEY,
        file_base64=_b64(test_sav_bytes),
        variable="gender",
        weight="weight_var",
    ))
    assert result


def test_analyze_frequencies_unknown_variable(test_sav_bytes):
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError):
        run(analyze_frequencies(
            api_key=TEST_KEY,
            file_base64=_b64(test_sav_bytes),
            variable="does_not_exist",
        ))


# ── analyze_crosstabs ─────────────────────────────────────────────────────────

def test_analyze_crosstabs(test_sav_bytes):
    result = run(analyze_crosstabs(
        api_key=TEST_KEY,
        file_base64=_b64(test_sav_bytes),
        row_variable="satisfaction",
        col_variable="gender",
    ))
    assert result
    assert isinstance(result, dict)


def test_analyze_crosstabs_significance_level(test_sav_bytes):
    result = run(analyze_crosstabs(
        api_key=TEST_KEY,
        file_base64=_b64(test_sav_bytes),
        row_variable="satisfaction",
        col_variable="gender",
        significance_level=0.90,
    ))
    assert result


def test_analyze_crosstabs_unknown_variable(test_sav_bytes):
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError):
        run(analyze_crosstabs(
            api_key=TEST_KEY,
            file_base64=_b64(test_sav_bytes),
            row_variable="nonexistent",
            col_variable="gender",
        ))


# ── export_data ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fmt", ["csv", "xlsx", "parquet"])
def test_export_data_formats(test_sav_bytes, fmt):
    result = run(export_data(
        api_key=TEST_KEY,
        file_base64=_b64(test_sav_bytes),
        target_format=fmt,
    ))
    assert "data_base64" in result
    assert "filename" in result
    assert result["size_bytes"] > 0
    # Verify it's valid base64
    decoded = base64.b64decode(result["data_base64"])
    assert len(decoded) > 0


def test_export_data_invalid_format(test_sav_bytes):
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="Invalid format"):
        run(export_data(
            api_key=TEST_KEY,
            file_base64=_b64(test_sav_bytes),
            target_format="docx",
        ))


# ── create_tabulation ─────────────────────────────────────────────────────────

def test_create_tabulation(test_sav_bytes):
    result = run(create_tabulation(
        api_key=TEST_KEY,
        file_base64=_b64(test_sav_bytes),
        banner="gender",
        stubs=["satisfaction"],
        title="Test Tabulation",
    ))
    # v2 wraps in build_mcp_response envelope
    assert result["tool"] == "spss_create_tabulation"
    assert result["filename"].endswith(".xlsx")
    data = result["results"]
    assert data["total_stubs"] >= 1
    # base64 fallback when Redis is not available
    assert "data_base64" in result
    excel_bytes = base64.b64decode(result["data_base64"])
    assert excel_bytes[:4] == b"PK\x03\x04"  # ZIP magic = valid xlsx


def test_create_tabulation_all_stubs(test_sav_bytes):
    result = run(create_tabulation(
        api_key=TEST_KEY,
        file_base64=_b64(test_sav_bytes),
        banner="gender",
    ))
    data = result["results"]
    assert data["total_stubs"] >= 1
    assert "data_base64" in result
    excel_bytes = base64.b64decode(result["data_base64"])
    assert excel_bytes[:4] == b"PK\x03\x04"


def test_create_tabulation_unknown_banner(test_sav_bytes):
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="not found"):
        run(create_tabulation(
            api_key=TEST_KEY,
            file_base64=_b64(test_sav_bytes),
            banner="nonexistent_banner",
        ))


def test_create_tabulation_unknown_stub(test_sav_bytes):
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="not found"):
        run(create_tabulation(
            api_key=TEST_KEY,
            file_base64=_b64(test_sav_bytes),
            banner="gender",
            stubs=["no_such_variable"],
        ))


# ── SSE endpoint reachability ─────────────────────────────────────────────────

def test_mcp_sse_endpoint_exists(client):
    """GET /mcp/sse should be mounted — FastMCP handles the SSE stream internally.

    We verify the route exists (not 404) without opening a persistent SSE
    connection, which would block the test runner indefinitely.
    """
    # POST to the messages endpoint as a proxy route-existence check
    response = client.post("/mcp/messages/", json={})
    # Any response except 404 confirms the MCP ASGI app is mounted at /mcp/
    assert response.status_code != 404
