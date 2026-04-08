"""Tests for Phase 4: Data Prep, Variable Groups, Waves, Explore, Segments, Metadata.

Tests cover:
1. Endpoint registration (all 6 routers in OpenAPI)
2. Auth requirements (JWT only)
3. Schema validation
4. Data prep service unit tests (apply rules, preview)
5. Segment service unit tests (resolve filters)
"""

import asyncio
import numpy as np
import pandas as pd
import pytest

from tests.conftest_db import make_test_jwt


# ─── Endpoint Registration ────────────────────────────────────────────────


class TestPhase4Endpoints:
    """All Phase 4 endpoints should be registered."""

    def test_data_prep_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/data-prep/rules" in paths
        assert "/v1/projects/{project_id}/data-prep/preview" in paths
        assert "/v1/projects/{project_id}/data-prep/reorder" in paths

    def test_variable_groups_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/variable-groups" in paths
        assert "/v1/projects/{project_id}/variable-groups/auto-detect" in paths

    def test_waves_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/waves" in paths
        assert "/v1/projects/{project_id}/waves/compare" in paths

    def test_explore_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/explore/variables" in paths
        assert "/v1/projects/{project_id}/explore/run" in paths
        assert "/v1/projects/{project_id}/explore/bookmarks" in paths

    def test_segments_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/segments" in paths
        assert "/v1/projects/{project_id}/segments/preview" in paths

    def test_metadata_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/metadata/overrides" in paths


# ─── Auth Requirements ────────────────────────────────────────────────────


class TestPhase4Auth:
    def test_data_prep_requires_jwt(self, client, auth_headers):
        """API key should be rejected on data prep endpoints."""
        r = client.get("/v1/projects/00000000-0000-0000-0000-000000000000/data-prep/rules",
                       headers=auth_headers)
        assert r.status_code == 403

    def test_segments_requires_jwt(self, client, auth_headers):
        r = client.get("/v1/projects/00000000-0000-0000-0000-000000000000/segments",
                       headers=auth_headers)
        assert r.status_code == 403

    def test_explore_requires_jwt(self, client, auth_headers):
        r = client.get("/v1/projects/00000000-0000-0000-0000-000000000000/explore/variables",
                       headers=auth_headers)
        assert r.status_code == 403


# ─── Schema Validation ────────────────────────────────────────────────────


class TestPhase4Schemas:
    def test_data_prep_rule_create(self):
        from schemas.data_prep import DataPrepRuleCreate
        rule = DataPrepRuleCreate(
            rule_type="cleaning",
            name="Remove under 18",
            config={"variable": "age", "operator": "less_than", "value": 18, "action": "drop"},
        )
        assert rule.rule_type == "cleaning"
        assert rule.config["operator"] == "less_than"

    def test_data_prep_rule_invalid_type(self):
        from schemas.data_prep import DataPrepRuleCreate
        with pytest.raises(Exception):
            DataPrepRuleCreate(rule_type="invalid_type")

    def test_segment_create(self):
        from schemas.segments import SegmentCreate
        seg = SegmentCreate(
            name="Women 25-34",
            conditions=[{"group": [
                {"variable": "gender", "operator": "in", "values": [2]},
                {"variable": "age", "operator": "gte", "value": 25},
                {"variable": "age", "operator": "lte", "value": 34},
            ]}],
        )
        assert len(seg.conditions) == 1
        assert len(seg.conditions[0]["group"]) == 3

    def test_explore_run_request(self):
        from schemas.explore import ExploreRunRequest
        req = ExploreRunRequest(variable="Q1", analysis_type="frequency")
        assert req.variable == "Q1"
        assert req.cross_variable is None

    def test_wave_create(self):
        from schemas.waves import WaveCreate
        wave = WaveCreate(wave_name="Q1 2026", wave_order=1)
        assert wave.wave_name == "Q1 2026"

    def test_variable_group_create(self):
        from schemas.variable_groups import VariableGroupCreate
        g = VariableGroupCreate(
            name="Brand Awareness",
            group_type="mrs",
            variables=["AWARE_A", "AWARE_B", "AWARE_C"],
        )
        assert len(g.variables) == 3


# ─── Data Prep Service Unit Tests ─────────────────────────────────────────


class TestDataPrepService:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        return pd.DataFrame({
            "age": np.random.randint(16, 70, size=100),
            "gender": np.random.choice([1, 2], size=100),
            "satisfaction": np.random.choice([1, 2, 3, 4, 5], size=100),
        })

    def test_cleaning_drop(self, sample_df):
        from services.data_prep_service import apply_rules
        rules = [{"rule_type": "cleaning", "config": {
            "variable": "age", "operator": "less_than", "value": 18, "action": "drop"
        }, "is_active": True, "order_index": 0}]
        result = apply_rules(sample_df, rules)
        assert (result["age"] >= 18).all()
        assert len(result) < len(sample_df)

    def test_cleaning_filter(self, sample_df):
        from services.data_prep_service import apply_rules
        rules = [{"rule_type": "cleaning", "config": {
            "variable": "gender", "operator": "equals", "value": 1, "action": "filter"
        }, "is_active": True, "order_index": 0}]
        result = apply_rules(sample_df, rules)
        assert (result["gender"] == 1).all()

    def test_net_creation(self, sample_df):
        from services.data_prep_service import apply_rules
        rules = [{"rule_type": "net", "config": {
            "variable": "satisfaction", "net_name": "top2box", "codes": [4, 5]
        }, "is_active": True, "order_index": 0}]
        result = apply_rules(sample_df, rules)
        assert "top2box" in result.columns
        assert set(result["top2box"].unique()).issubset({0, 1})

    def test_recode(self, sample_df):
        from services.data_prep_service import apply_rules
        rules = [{"rule_type": "recode", "config": {
            "variable": "satisfaction",
            "target_variable": "sat_grouped",
            "mappings": [
                {"old_values": [1, 2], "new_value": 1},
                {"old_values": [3], "new_value": 2},
                {"old_values": [4, 5], "new_value": 3},
            ],
        }, "is_active": True, "order_index": 0}]
        result = apply_rules(sample_df, rules)
        assert "sat_grouped" in result.columns
        assert set(result["sat_grouped"].unique()).issubset({1, 2, 3})

    def test_computed_variable(self, sample_df):
        from services.data_prep_service import apply_rules
        rules = [{"rule_type": "computed", "config": {
            "name": "young_male",
            "conditions": [
                {"variable": "age", "operator": "less_than", "value": 30},
                {"variable": "gender", "operator": "equals", "value": 1},
            ],
            "combine": "and",
        }, "is_active": True, "order_index": 0}]
        result = apply_rules(sample_df, rules)
        assert "young_male" in result.columns

    def test_inactive_rule_skipped(self, sample_df):
        from services.data_prep_service import apply_rules
        rules = [{"rule_type": "cleaning", "config": {
            "variable": "age", "operator": "less_than", "value": 18, "action": "drop"
        }, "is_active": False, "order_index": 0}]
        result = apply_rules(sample_df, rules)
        assert len(result) == len(sample_df)  # No change

    def test_preview_rule(self, sample_df):
        from services.data_prep_service import preview_rule
        result = preview_rule(sample_df, "cleaning", {
            "variable": "age", "operator": "less_than", "value": 18, "action": "drop"
        })
        assert result["before"]["rows"] == 100
        assert result["after"]["rows"] < 100
        assert result["rows_removed"] > 0

    def test_cumulative_preview(self, sample_df):
        from services.data_prep_service import preview_rule
        existing = [{"rule_type": "cleaning", "config": {
            "variable": "gender", "operator": "equals", "value": 1, "action": "filter"
        }, "is_active": True, "order_index": 0}]
        result = preview_rule(sample_df, "cleaning", {
            "variable": "age", "operator": "less_than", "value": 30, "action": "drop"
        }, existing_rules=existing)
        # existing filter keeps only gender==1, then age drop removes more
        assert result["before"]["rows"] < 100


# ─── Segment Service Unit Tests ───────────────────────────────────────────


class TestSegmentService:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        return pd.DataFrame({
            "gender": np.random.choice([1, 2], size=100),
            "age": np.random.randint(18, 65, size=100),
            "city": np.random.choice(["bogota", "medellin", "cali"], size=100),
        })

    def test_single_condition(self, sample_df):
        from services.segment_service import resolve_segment_filter
        conditions = [{"group": [{"variable": "gender", "operator": "in", "values": [1]}]}]
        result = resolve_segment_filter(sample_df, conditions)
        assert (result["gender"] == 1).all()

    def test_and_conditions(self, sample_df):
        from services.segment_service import resolve_segment_filter
        conditions = [{"group": [
            {"variable": "gender", "operator": "in", "values": [2]},
            {"variable": "city", "operator": "in", "values": ["bogota"]},
        ]}]
        result = resolve_segment_filter(sample_df, conditions)
        assert (result["gender"] == 2).all()
        assert (result["city"] == "bogota").all()

    def test_range_filter(self, sample_df):
        from services.segment_service import resolve_segment_filter
        conditions = [{"group": [
            {"variable": "age", "operator": "gte", "value": 25},
            {"variable": "age", "operator": "lte", "value": 34},
        ]}]
        result = resolve_segment_filter(sample_df, conditions)
        assert (result["age"] >= 25).all()
        assert (result["age"] <= 34).all()

    def test_empty_conditions(self, sample_df):
        from services.segment_service import resolve_segment_filter
        result = resolve_segment_filter(sample_df, [])
        assert len(result) == len(sample_df)

    def test_preview_segment(self, sample_df):
        from services.segment_service import preview_segment
        conditions = [{"group": [{"variable": "gender", "operator": "in", "values": [1]}]}]
        result = preview_segment(sample_df, conditions)
        assert result["total_rows"] == 100
        assert result["matching_rows"] > 0
        assert result["match_percentage"] > 0
