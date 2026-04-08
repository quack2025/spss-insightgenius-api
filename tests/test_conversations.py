"""Tests for Phase 3: Conversations & NL Chat Engine.

Tests cover:
1. Endpoint registration (routes exist)
2. Auth requirements (JWT only)
3. Schema validation
4. Executor unit tests (fuzzy matching, analysis dispatch)
5. Responder unit tests (chart building, code generation)
6. Interpreter output structure
"""

import asyncio
import pytest

from schemas.conversations import (
    QueryRequest,
    ConversationCreate,
    QueryResponse,
    ConversationOut,
)
from tests.conftest_db import make_test_jwt


# ─── Endpoint Registration ────────────────────────────────────────────────


class TestConversationEndpoints:
    """Verify conversation endpoints exist in OpenAPI."""

    def test_openapi_has_conversation_routes(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        paths = response.json().get("paths", {})

        assert "/v1/projects/{project_id}/conversations" in paths
        assert "/v1/conversations/{conversation_id}" in paths
        assert "/v1/conversations/{conversation_id}/query" in paths
        assert "/v1/conversations/{conversation_id}/suggestions" in paths

    def test_query_endpoint_is_post(self, client):
        response = client.get("/openapi.json")
        methods = response.json()["paths"].get("/v1/conversations/{conversation_id}/query", {})
        assert "post" in methods


# ─── Auth Requirements ────────────────────────────────────────────────────


class TestConversationAuth:
    def test_api_key_rejected(self, client, auth_headers):
        """Conversation endpoints require JWT, not API key."""
        response = client.get("/v1/projects/00000000-0000-0000-0000-000000000000/conversations",
                              headers=auth_headers)
        assert response.status_code == 403

    def test_no_auth_rejected(self, client):
        response = client.post("/v1/conversations/00000000-0000-0000-0000-000000000000/query",
                               json={"question": "test"})
        assert response.status_code == 401


# ─── Schema Validation ────────────────────────────────────────────────────


class TestConversationSchemas:
    def test_query_request_valid(self):
        req = QueryRequest(question="What is the distribution of gender?")
        assert req.question == "What is the distribution of gender?"
        assert req.segment_id is None
        assert req.confidence_level is None

    def test_query_request_with_params(self):
        req = QueryRequest(
            question="Cross awareness by gender",
            confidence_level=0.99,
        )
        assert req.confidence_level == 0.99

    def test_query_request_empty_rejected(self):
        with pytest.raises(Exception):
            QueryRequest(question="")

    def test_conversation_create_default(self):
        c = ConversationCreate()
        assert c.title == "New conversation"


# ─── Executor Unit Tests ─────────────────────────────────────────────────


class TestExecutor:
    """Test the analysis executor directly (no HTTP, no DB)."""

    def test_fuzzy_resolve_exact(self):
        from services.nl_chat.executor import _fuzzy_resolve

        class FakeMeta:
            column_names_to_labels = {}

        cols = ["gender", "age_group", "satisfaction"]
        assert _fuzzy_resolve("gender", cols, FakeMeta()) == "gender"

    def test_fuzzy_resolve_case_insensitive(self):
        from services.nl_chat.executor import _fuzzy_resolve

        class FakeMeta:
            column_names_to_labels = {}

        cols = ["Gender", "Age_Group"]
        assert _fuzzy_resolve("gender", cols, FakeMeta()) == "Gender"

    def test_fuzzy_resolve_accent(self):
        from services.nl_chat.executor import _fuzzy_resolve

        class FakeMeta:
            column_names_to_labels = {}

        cols = ["GENERO", "EDAD"]
        assert _fuzzy_resolve("género", cols, FakeMeta()) == "GENERO"

    def test_fuzzy_resolve_label_match(self):
        from services.nl_chat.executor import _fuzzy_resolve

        class FakeMeta:
            column_names_to_labels = {"P1": "Overall Satisfaction", "P2": "Gender"}

        cols = ["P1", "P2"]
        assert _fuzzy_resolve("satisfaction", cols, FakeMeta()) == "P1"

    def test_fuzzy_resolve_no_match(self):
        from services.nl_chat.executor import _fuzzy_resolve

        class FakeMeta:
            column_names_to_labels = {}

        cols = ["Q1", "Q2"]
        # Should return original when no match
        assert _fuzzy_resolve("nonexistent", cols, FakeMeta()) == "nonexistent"

    def test_execute_frequency(self, test_sav_bytes):
        """Execute a frequency analysis against real SPSS data."""
        from services.quantipy_engine import QuantiProEngine
        from services.nl_chat.executor import execute_analysis_plan

        data = QuantiProEngine.load_spss(test_sav_bytes)
        plan = [{"type": "frequency", "variable": "gender"}]

        results = asyncio.get_event_loop().run_until_complete(
            execute_analysis_plan(data, plan)
        )

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["type"] == "frequency"
        assert results[0]["result"] is not None
        # Engine returns "frequencies" key
        assert "frequencies" in results[0]["result"] or "rows" in results[0]["result"]

    def test_execute_crosstab(self, test_sav_bytes):
        """Execute a crosstab analysis with significance."""
        from services.quantipy_engine import QuantiProEngine
        from services.nl_chat.executor import execute_analysis_plan

        data = QuantiProEngine.load_spss(test_sav_bytes)
        plan = [{
            "type": "crosstab_with_significance",
            "variable": "satisfaction",
            "cross_variable": "gender",
        }]

        results = asyncio.get_event_loop().run_until_complete(
            execute_analysis_plan(data, plan)
        )

        assert len(results) == 1
        assert results[0]["success"] is True
        result = results[0]["result"]
        # Engine may return "table" or "rows" depending on path
        assert any(k in result for k in ("table", "rows", "col_labels", "total_responses"))

    def test_execute_nps(self, test_sav_bytes):
        """Execute NPS analysis."""
        from services.quantipy_engine import QuantiProEngine
        from services.nl_chat.executor import execute_analysis_plan

        data = QuantiProEngine.load_spss(test_sav_bytes)
        plan = [{"type": "nps", "variable": "recommend"}]

        results = asyncio.get_event_loop().run_until_complete(
            execute_analysis_plan(data, plan)
        )

        assert len(results) == 1
        assert results[0]["success"] is True
        assert "nps_score" in results[0]["result"]

    def test_execute_descriptive(self, test_sav_bytes):
        """Execute descriptive stats."""
        from services.quantipy_engine import QuantiProEngine
        from services.nl_chat.executor import execute_analysis_plan

        data = QuantiProEngine.load_spss(test_sav_bytes)
        plan = [{"type": "descriptive", "variable": "satisfaction"}]

        results = asyncio.get_event_loop().run_until_complete(
            execute_analysis_plan(data, plan)
        )

        assert len(results) == 1
        assert results[0]["success"] is True
        r = results[0]["result"]
        assert "mean" in r
        assert "std" in r
        assert "median" in r

    def test_execute_missing_variable(self, test_sav_bytes):
        """Missing variable should return error, not crash."""
        from services.quantipy_engine import QuantiProEngine
        from services.nl_chat.executor import execute_analysis_plan

        data = QuantiProEngine.load_spss(test_sav_bytes)
        plan = [{"type": "frequency", "variable": "nonexistent_var"}]

        results = asyncio.get_event_loop().run_until_complete(
            execute_analysis_plan(data, plan)
        )

        assert len(results) == 1
        assert results[0]["success"] is False
        assert "not found" in results[0]["error"]

    def test_execute_multiple_analyses(self, test_sav_bytes):
        """Multiple analyses should all execute."""
        from services.quantipy_engine import QuantiProEngine
        from services.nl_chat.executor import execute_analysis_plan

        data = QuantiProEngine.load_spss(test_sav_bytes)
        plan = [
            {"type": "frequency", "variable": "gender"},
            {"type": "frequency", "variable": "satisfaction"},
            {"type": "nps", "variable": "recommend"},
        ]

        results = asyncio.get_event_loop().run_until_complete(
            execute_analysis_plan(data, plan)
        )

        assert len(results) == 3
        assert all(r["success"] for r in results)


# ─── Responder Unit Tests ────────────────────────────────────────────────


class TestResponder:
    """Test chart building and code generation."""

    def test_build_frequency_chart(self):
        from services.nl_chat.responder import _build_chart

        result = {
            "type": "frequency",
            "variable": "gender",
            "result": {
                "frequencies": [
                    {"value": 1, "label": "Male", "count": 55, "percentage": 55.0},
                    {"value": 2, "label": "Female", "count": 45, "percentage": 45.0},
                ],
                "base": 100,
            },
        }
        chart = _build_chart(result)
        assert chart is not None
        assert chart["chart_type"] == "bar"
        assert len(chart["data"]) == 2
        assert chart["data"][0]["name"] == "Male"

    def test_build_nps_chart(self):
        from services.nl_chat.responder import _build_chart

        result = {
            "type": "nps",
            "result": {
                "nps_score": 45.0,
                "promoters_pct": 60.0,
                "passives_pct": 25.0,
                "detractors_pct": 15.0,
            },
        }
        chart = _build_chart(result)
        assert chart is not None
        assert chart["chart_type"] == "nps_gauge"
        assert chart["nps_score"] == 45.0

    def test_generate_python_code(self):
        from services.nl_chat.responder import _generate_python_code

        results = [
            {"type": "frequency", "variable": "gender"},
            {"type": "nps", "variable": "recommend"},
        ]
        code = _generate_python_code(results)
        assert code is not None
        assert "pyreadstat" in code
        assert "gender" in code
        assert "recommend" in code

    def test_fallback_summary(self):
        from services.nl_chat.responder import _fallback_summary

        results = [
            {"type": "frequency", "variable": "gender", "result": {"total_responses": 100}},
        ]
        summary = _fallback_summary(results, "en")
        assert "Frequency of gender" in summary

    def test_fallback_summary_spanish(self):
        from services.nl_chat.responder import _fallback_summary

        results = [
            {"type": "nps", "variable": "Q1", "result": {"nps_score": 42}},
        ]
        summary = _fallback_summary(results, "es")
        assert "NPS: 42" in summary


# ─── Data Manager ─────────────────────────────────────────────────────────


class TestDataManager:
    def test_cache_and_retrieve(self, test_sav_bytes):
        """Data should be cached after first load."""
        from services.data_manager import get_project_data, invalidate_project_cache

        # Clear any existing cache
        invalidate_project_cache("test-project-123")

        # First load (from bytes)
        data1 = asyncio.get_event_loop().run_until_complete(
            get_project_data("test-project-123", file_bytes=test_sav_bytes)
        )
        assert data1.df is not None
        assert len(data1.df) == 100

        # Second load (from cache — no bytes needed)
        data2 = asyncio.get_event_loop().run_until_complete(
            get_project_data("test-project-123")
        )
        assert len(data2.df) == 100

        # Cleanup
        invalidate_project_cache("test-project-123")

    def test_invalidate_cache(self, test_sav_bytes):
        """Invalidation should force reload."""
        from services.data_manager import get_project_data, invalidate_project_cache

        asyncio.get_event_loop().run_until_complete(
            get_project_data("test-inv-456", file_bytes=test_sav_bytes)
        )
        invalidate_project_cache("test-inv-456")

        # Without bytes and without cache, should fail
        with pytest.raises(ValueError, match="No data available"):
            asyncio.get_event_loop().run_until_complete(
                get_project_data("test-inv-456")
            )
