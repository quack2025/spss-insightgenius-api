"""Tests for Phase 5: Exports, Generate Tables, Reports.

Tests cover:
1. Endpoint registration
2. Auth requirements
3. Schema validation
4. Report generator plan building (unit)
5. Table wizard config conversion (unit)
"""

import asyncio
import pytest
from tests.conftest_db import make_test_jwt


class TestPhase5Endpoints:
    def test_tables_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/tables/preview" in paths
        assert "/v1/projects/{project_id}/tables/generate" in paths
        assert "/v1/projects/{project_id}/tables/export" in paths
        assert "/v1/projects/{project_id}/tables/templates" in paths

    def test_exports_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/exports" in paths
        assert "/v1/projects/{project_id}/exports/banners" in paths
        assert "/v1/projects/{project_id}/exports/stubs" in paths

    def test_reports_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/reports" in paths
        assert "/v1/projects/{project_id}/reports/{report_id}" in paths


class TestPhase5Auth:
    def test_tables_require_jwt(self, client, auth_headers):
        r = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/tables/preview",
            json={"banners": ["gender"]},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_exports_require_jwt(self, client, auth_headers):
        r = client.get("/v1/projects/00000000-0000-0000-0000-000000000000/exports",
                       headers=auth_headers)
        assert r.status_code == 403

    def test_reports_require_jwt(self, client, auth_headers):
        r = client.get("/v1/projects/00000000-0000-0000-0000-000000000000/reports",
                       headers=auth_headers)
        assert r.status_code == 403


class TestPhase5Schemas:
    def test_generate_tables_config(self):
        from schemas.exports import GenerateTablesConfig
        config = GenerateTablesConfig(
            banners=["gender", "age_group"],
            stubs=["satisfaction", "recommend"],
            significance_level=0.95,
            include_means=True,
        )
        assert len(config.banners) == 2
        assert config.include_means is True

    def test_generate_tables_all_stubs(self):
        from schemas.exports import GenerateTablesConfig
        config = GenerateTablesConfig(banners=["gender"])
        assert config.stubs == "_all_"

    def test_export_create(self):
        from schemas.exports import ExportCreate
        e = ExportCreate(export_type="excel", config={"format": "xlsx"})
        assert e.export_type == "excel"

    def test_report_create(self):
        from schemas.exports import ReportCreate
        r = ReportCreate(title="Q1 Report", depth="detailed")
        assert r.depth == "detailed"

    def test_template_create(self):
        from schemas.exports import TableTemplateCreate
        t = TableTemplateCreate(name="Standard Template", config={"banners": ["gender"]})
        assert t.name == "Standard Template"


class TestReportGenerator:
    """Unit tests for the report generator plan builder."""

    def test_build_report_plan(self, test_sav_bytes):
        from services.quantipy_engine import QuantiProEngine
        from services.report_generator import _build_report_plan

        data = QuantiProEngine.load_spss(test_sav_bytes)
        meta = QuantiProEngine.extract_metadata(data)
        variables_info = meta.get("variables", [])

        plan = _build_report_plan(variables_info, data)
        assert len(plan) >= 1
        assert len(plan) <= 8
        # Should have at least one frequency
        types = [p["type"] for p in plan]
        assert "frequency" in types

    def test_plan_includes_nps(self, test_sav_bytes):
        """Plan should include NPS if recommend variable exists."""
        from services.quantipy_engine import QuantiProEngine
        from services.report_generator import _build_report_plan

        data = QuantiProEngine.load_spss(test_sav_bytes)
        meta = QuantiProEngine.extract_metadata(data)
        variables_info = meta.get("variables", [])

        plan = _build_report_plan(variables_info, data)
        types = [p["type"] for p in plan]
        # recommend var should trigger NPS
        assert "nps" in types

    def test_plan_includes_crosstab(self, test_sav_bytes):
        """Plan should include crosstab if demo + key var exist."""
        from services.quantipy_engine import QuantiProEngine
        from services.report_generator import _build_report_plan

        data = QuantiProEngine.load_spss(test_sav_bytes)
        meta = QuantiProEngine.extract_metadata(data)
        variables_info = meta.get("variables", [])

        plan = _build_report_plan(variables_info, data)
        types = [p["type"] for p in plan]
        assert "crosstab_with_significance" in types


class TestTableWizard:
    def test_config_to_spec(self, test_sav_bytes):
        from services.quantipy_engine import QuantiProEngine
        from services.table_wizard import _config_to_spec

        data = QuantiProEngine.load_spss(test_sav_bytes)
        config = {
            "banners": ["gender"],
            "stubs": ["satisfaction", "recommend"],
            "significance_level": 0.95,
        }
        spec = _config_to_spec(data, config)
        assert spec.significance_level == 0.95
        assert "satisfaction" in spec.stubs
        assert "recommend" in spec.stubs

    def test_config_all_stubs(self, test_sav_bytes):
        from services.quantipy_engine import QuantiProEngine
        from services.table_wizard import _config_to_spec

        data = QuantiProEngine.load_spss(test_sav_bytes)
        config = {"banners": ["gender"], "stubs": "_all_"}
        spec = _config_to_spec(data, config)
        # All non-banner columns should be stubs
        assert "satisfaction" in spec.stubs
        assert "gender" not in spec.stubs
