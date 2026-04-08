"""Tests for Phase 6 (Teams/Dashboards/Share/Users) + Phase 7 (Merge/Clustering).

Tests cover endpoint registration, auth, schemas, and clustering unit tests.
"""

import numpy as np
import pandas as pd
import pytest
from tests.conftest_db import make_test_jwt


class TestPhase6Endpoints:
    def test_teams_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/teams" in paths
        assert "/v1/teams/{team_id}" in paths
        assert "/v1/teams/{team_id}/members" in paths

    def test_dashboards_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/dashboards" in paths
        assert "/v1/projects/{project_id}/dashboards/{dashboard_id}" in paths
        assert "/v1/projects/{project_id}/dashboards/{dashboard_id}/publish" in paths
        assert "/v1/projects/{project_id}/dashboards/{dashboard_id}/widgets" in paths

    def test_share_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/share" in paths
        assert "/v1/public/dashboards/{share_token}" in paths

    def test_users_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/users/me" in paths
        assert "/v1/users/me/preferences" in paths

    def test_help_endpoint(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/help-chat" in paths


class TestPhase7Endpoints:
    def test_merge_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/merge/validate" in paths
        assert "/v1/projects/{project_id}/merge" in paths

    def test_clustering_endpoints(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/projects/{project_id}/clustering/auto-k" in paths
        assert "/v1/projects/{project_id}/clustering/run" in paths


class TestPhase6Auth:
    def test_teams_require_jwt(self, client, auth_headers):
        r = client.get("/v1/teams", headers=auth_headers)
        assert r.status_code == 403

    def test_dashboards_require_jwt(self, client, auth_headers):
        r = client.get("/v1/projects/00000000-0000-0000-0000-000000000000/dashboards",
                       headers=auth_headers)
        assert r.status_code == 403

    def test_users_require_jwt(self, client, auth_headers):
        r = client.get("/v1/users/me", headers=auth_headers)
        assert r.status_code == 403

    def test_public_dashboard_no_auth(self, client):
        """Public dashboard endpoint should NOT require auth."""
        r = client.get("/v1/public/dashboards/nonexistent_token")
        # Should return 404 (not found), NOT 401 (no auth required)
        assert r.status_code in (404, 500)  # 500 if no DB, 404 if DB but not found


class TestPhase6Schemas:
    def test_team_create(self):
        from schemas.teams import TeamCreate
        t = TeamCreate(name="Research Team", description="Our team")
        assert t.name == "Research Team"

    def test_dashboard_create(self):
        from schemas.dashboards import DashboardCreate
        d = DashboardCreate(name="Q1 Dashboard", widgets=[{"type": "chart", "config": {}}])
        assert len(d.widgets) == 1

    def test_share_link_create(self):
        from schemas.dashboards import ShareLinkCreate
        s = ShareLinkCreate(password="secret123", expires_in_hours=48)
        assert s.expires_in_hours == 48

    def test_user_preferences_update(self):
        from schemas.dashboards import UserPreferencesUpdate
        p = UserPreferencesUpdate(language="es", confidence_level="99")
        assert p.language == "es"


class TestPhase7Schemas:
    def test_merge_validate(self):
        from routers.merge import MergeValidateRequest
        import uuid
        r = MergeValidateRequest(source_project_id=uuid.uuid4(), merge_type="append")
        assert r.merge_type == "append"

    def test_cluster_request(self):
        from routers.clustering import ClusterRequest
        c = ClusterRequest(variables=["Q1", "Q2", "Q3"], n_clusters=4, method="kmeans")
        assert c.n_clusters == 4

    def test_auto_k_request(self):
        from routers.clustering import AutoKRequest
        a = AutoKRequest(variables=["Q1", "Q2"], max_k=8)
        assert a.max_k == 8


class TestClusteringUnit:
    """Unit tests for clustering functions."""

    def test_kmeans_basic(self):
        from routers.clustering import _run_cluster
        np.random.seed(42)
        df = pd.DataFrame({
            "x": np.concatenate([np.random.normal(0, 1, 50), np.random.normal(5, 1, 50)]),
            "y": np.concatenate([np.random.normal(0, 1, 50), np.random.normal(5, 1, 50)]),
        })
        result = _run_cluster(df, ["x", "y"], "kmeans", 2, "ward")
        assert result["method"] == "kmeans"
        assert result["n_clusters"] == 2
        assert result["n_rows"] == 100
        assert sum(result["cluster_sizes"].values()) == 100

    def test_hierarchical_basic(self):
        from routers.clustering import _run_cluster
        np.random.seed(42)
        df = pd.DataFrame({
            "x": np.random.randn(30),
            "y": np.random.randn(30),
        })
        result = _run_cluster(df, ["x", "y"], "hierarchical", 3, "ward")
        assert result["method"] == "hierarchical"
        assert "dendrogram" in result
        assert sum(result["cluster_sizes"].values()) == 30

    def test_elbow_method(self):
        from routers.clustering import _compute_elbow
        np.random.seed(42)
        df = pd.DataFrame({
            "x": np.random.randn(50),
            "y": np.random.randn(50),
        })
        result = _compute_elbow(df, ["x", "y"], 6)
        assert "inertias" in result
        assert "suggested_k" in result
        assert len(result["inertias"]) >= 2

    def test_too_few_rows(self):
        from routers.clustering import _run_cluster
        df = pd.DataFrame({"x": [1], "y": [2]})
        with pytest.raises(ValueError, match="Not enough data"):
            _run_cluster(df, ["x", "y"], "kmeans", 3, "ward")
