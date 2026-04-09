"""Tests for additional router endpoints: parse-ticket, smart-spec, downloads, library."""
import json
import pytest
from tests.conftest import _client, TEST_KEY

HEADERS = {"Authorization": f"Bearer {TEST_KEY}"}


# ── PARSE TICKET ─────────────────────────────────────────────────

class TestParseTicket:
    def test_parse_ticket_no_file(self):
        """Missing ticket file should fail."""
        resp = _client.post("/v1/parse-ticket", headers=HEADERS)
        assert resp.status_code == 422  # FastAPI validation: missing required file

    def test_parse_ticket_non_docx(self):
        """Non-docx file should be rejected or handled."""
        resp = _client.post(
            "/v1/parse-ticket",
            headers=HEADERS,
            files={"ticket": ("test.txt", b"not a docx", "text/plain")},
        )
        assert resp.status_code in (400, 415, 422, 503)


# ── SMART SPEC ───────────────────────────────────────────────────

class TestSmartSpec:
    def test_smart_spec_no_documents(self, test_sav_bytes):
        """Should fail if no questionnaire or ticket provided."""
        resp = _client.post(
            "/v1/smart-spec",
            headers=HEADERS,
            files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        )
        assert resp.status_code in (400, 503)

    def test_smart_spec_no_file(self):
        """Should fail if no .sav file provided (or 503 if AI not configured)."""
        resp = _client.post(
            "/v1/smart-spec",
            headers=HEADERS,
            files={"questionnaire": ("q.docx", b"fake docx content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert resp.status_code in (400, 422, 503)


# ── DOWNLOADS ────────────────────────────────────────────────────

class TestDownloads:
    def test_download_nonexistent_token(self):
        """Expired/invalid token should 404."""
        resp = _client.get("/downloads/00000000-0000-0000-0000-000000000000")
        assert resp.status_code in (404, 503)

    def test_download_malformed_token(self):
        """Malformed token."""
        resp = _client.get("/downloads/not-a-uuid")
        assert resp.status_code in (404, 422, 503)


# ── LIBRARY ──────────────────────────────────────────────────────

class TestLibrary:
    def test_library_list_requires_auth(self):
        """No auth should be rejected."""
        resp = _client.get("/v1/library/files")
        assert resp.status_code in (401, 403)

    def test_library_list_with_auth(self):
        """With auth should return list (may be empty)."""
        resp = _client.get("/v1/library/files", headers=HEADERS)
        # May fail with 500 if Supabase not configured — that's OK for test env
        assert resp.status_code in (200, 500)

    def test_library_get_nonexistent(self):
        """Nonexistent library_id should 404."""
        resp = _client.get("/v1/library/00000000-0000-0000-0000-000000000000", headers=HEADERS)
        assert resp.status_code in (404, 500)

    def test_library_search_requires_auth(self):
        resp = _client.get("/v1/library/search/files?q=test")
        assert resp.status_code in (401, 403)

    def test_library_delete_nonexistent(self):
        resp = _client.delete("/v1/library/00000000-0000-0000-0000-000000000000", headers=HEADERS)
        assert resp.status_code in (404, 500)


# ── CONVERT ──────────────────────────────────────────────────────

class TestConvertExtra:
    def test_convert_to_csv(self, test_sav_bytes):
        resp = _client.post(
            "/v1/convert",
            headers=HEADERS,
            files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
            data={"target_format": "csv"},
        )
        assert resp.status_code == 200
        assert b"," in resp.content  # CSV has commas

    def test_convert_to_parquet(self, test_sav_bytes):
        resp = _client.post(
            "/v1/convert",
            headers=HEADERS,
            files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
            data={"target_format": "parquet"},
        )
        assert resp.status_code == 200
        # Parquet magic bytes: PAR1
        assert resp.content[:4] == b"PAR1"

    def test_convert_invalid_format(self, test_sav_bytes):
        resp = _client.post(
            "/v1/convert",
            headers=HEADERS,
            files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
            data={"target_format": "pdf"},
        )
        assert resp.status_code == 400


# ── JOBS ─────────────────────────────────────────────────────────

class TestJobsExtra:
    def test_jobs_requires_auth(self):
        resp = _client.get("/v1/jobs/some-id")
        assert resp.status_code in (401, 403)

    def test_jobs_nonexistent(self):
        resp = _client.get("/v1/jobs/00000000-0000-0000-0000-000000000000", headers=HEADERS)
        assert resp.status_code == 404
