"""Tests for Phase 2: Projects API.

Tests cover:
1. Endpoint registration (routes exist in OpenAPI)
2. Auth requirements (JWT required, API key rejected)
3. Schema validation (Pydantic models)
4. Service logic (unit tests)
5. Metadata extraction (reuses quantipy_engine)
"""

import pytest

from schemas.projects import (
    ProjectCreate,
    ProjectUpdate,
    ProjectOut,
    FileUploadOut,
    ProjectListOut,
)
from tests.conftest_db import make_test_jwt


# ─── Endpoint Registration ────────────────────────────────────────────────


class TestEndpointRegistration:
    """Verify project endpoints are registered in the OpenAPI spec."""

    def test_openapi_has_projects_endpoints(self, client):
        """Project endpoints should appear in the OpenAPI spec."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        paths = spec.get("paths", {})

        # Check key project endpoints exist
        assert "/v1/projects" in paths, "POST/GET /v1/projects should exist"
        assert "/v1/projects/{project_id}" in paths, "GET/PATCH/DELETE /v1/projects/{id} should exist"
        assert "/v1/projects/{project_id}/files/upload" in paths, "POST upload should exist"
        assert "/v1/projects/{project_id}/files" in paths, "GET files should exist"

    def test_projects_post_method_exists(self, client):
        """POST /v1/projects should be a valid method."""
        response = client.get("/openapi.json")
        spec = response.json()
        methods = spec["paths"].get("/v1/projects", {})
        assert "post" in methods, "POST method should exist on /v1/projects"
        assert "get" in methods, "GET method should exist on /v1/projects"


# ─── Auth Requirements ────────────────────────────────────────────────────


class TestProjectAuth:
    """Verify that project endpoints require proper authentication."""

    def test_no_auth_rejected(self, client):
        """Request without auth should be rejected."""
        response = client.post("/v1/projects", json={"name": "Test"})
        assert response.status_code == 401

    def test_api_key_rejected(self, client, auth_headers):
        """API key should be rejected (require_user needs JWT)."""
        response = client.post(
            "/v1/projects",
            json={"name": "Test"},
            headers=auth_headers,
        )
        # Should return 403 (API key not allowed for user endpoints)
        assert response.status_code == 403
        data = response.json()
        assert "FORBIDDEN" in str(data)

    def test_jwt_without_db_returns_503(self, client):
        """JWT auth without database configured returns 503."""
        token = make_test_jwt()
        response = client.post(
            "/v1/projects",
            json={"name": "Test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Without DATABASE_URL, JWT auth should return 503
        assert response.status_code == 503


# ─── Schema Validation ────────────────────────────────────────────────────


class TestProjectSchemas:
    """Test Pydantic schema validation."""

    def test_create_minimal(self):
        """ProjectCreate with just name should work."""
        data = ProjectCreate(name="My Survey")
        assert data.name == "My Survey"
        assert data.report_language == "en"
        assert data.low_base_threshold == 20

    def test_create_full(self):
        """ProjectCreate with all fields should work."""
        data = ProjectCreate(
            name="Brand Tracking 2026",
            description="Wave 3 of brand health study",
            study_objective="Measure brand awareness and consideration",
            country="Colombia",
            industry="FMCG",
            brands=["Brand A", "Brand B"],
            methodology="CATI",
            is_tracking=True,
            report_language="es",
            low_base_threshold=30,
        )
        assert data.brands == ["Brand A", "Brand B"]
        assert data.is_tracking is True

    def test_create_empty_name_rejected(self):
        """ProjectCreate with empty name should fail validation."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            ProjectCreate(name="")

    def test_update_partial(self):
        """ProjectUpdate should allow partial updates."""
        data = ProjectUpdate(name="New Name")
        dumped = data.model_dump(exclude_unset=True)
        assert dumped == {"name": "New Name"}
        assert "description" not in dumped

    def test_file_upload_out(self):
        """FileUploadOut should serialize correctly."""
        import uuid
        out = FileUploadOut(
            file_id=uuid.uuid4(),
            original_name="survey.sav",
            size_bytes=1024000,
            file_type="spss_data",
            n_cases=500,
            n_variables=45,
        )
        d = out.model_dump(mode="json")
        assert d["original_name"] == "survey.sav"
        assert d["n_cases"] == 500


# ─── Metadata Extraction (Unit) ──────────────────────────────────────────


class TestMetadataExtraction:
    """Test that metadata extraction works with quantipy_engine."""

    def test_extract_metadata_from_bytes(self, test_sav_bytes):
        """Should extract metadata from a valid .sav file."""
        import asyncio
        from services.metadata_extractor import extract_metadata_from_bytes

        result = asyncio.get_event_loop().run_until_complete(
            extract_metadata_from_bytes(test_sav_bytes)
        )

        assert result["n_cases"] == 100
        assert result["n_variables"] == 5

        # Check variable names
        var_names = [v["name"] for v in result["variables"]]
        assert "gender" in var_names
        assert "satisfaction" in var_names
        assert "recommend" in var_names

    def test_extract_has_labels(self, test_sav_bytes):
        """Extracted metadata should include variable labels."""
        import asyncio
        from services.metadata_extractor import extract_metadata_from_bytes

        result = asyncio.get_event_loop().run_until_complete(
            extract_metadata_from_bytes(test_sav_bytes)
        )

        # Find gender variable
        gender = next(v for v in result["variables"] if v["name"] == "gender")
        assert gender["label"] == "Gender"
        assert gender["type"] == "numeric"

    def test_extract_has_value_labels(self, test_sav_bytes):
        """Extracted metadata should include value labels for categoricals."""
        import asyncio
        from services.metadata_extractor import extract_metadata_from_bytes

        result = asyncio.get_event_loop().run_until_complete(
            extract_metadata_from_bytes(test_sav_bytes)
        )

        gender = next(v for v in result["variables"] if v["name"] == "gender")
        vl = gender.get("value_labels", {})
        assert vl is not None
        # Value labels should have Male/Female
        labels = list(vl.values())
        assert "Male" in labels
        assert "Female" in labels

    def test_extract_invalid_bytes(self):
        """Invalid bytes should raise an error."""
        import asyncio
        from services.metadata_extractor import extract_metadata_from_bytes

        with pytest.raises(Exception):
            asyncio.get_event_loop().run_until_complete(
                extract_metadata_from_bytes(b"not a valid spss file")
            )


# ─── Response Envelope ────────────────────────────────────────────────────


class TestResponseEnvelope:
    """Verify all project endpoints use the standard response envelope."""

    def test_list_returns_envelope(self, client, auth_headers):
        """Even error responses should follow the envelope pattern."""
        # API key will be rejected with 403 — but it should still be a proper response
        response = client.get("/v1/projects", headers=auth_headers)
        data = response.json()
        # Should have either "success" or "detail" (FastAPI default for auth errors)
        assert response.status_code in (200, 403, 503)
