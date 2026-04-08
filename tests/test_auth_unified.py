"""Tests for Phase 1: Dual Authentication (API keys + Supabase JWT).

Tests verify:
1. Existing API key auth continues working (no regression)
2. JWT verification logic works correctly
3. Invalid/expired JWTs are rejected
4. The unified auth context dispatches correctly
"""

import time
import jwt as pyjwt
import pytest

from services.jwt_auth import verify_supabase_jwt, JWTVerificationError
from tests.conftest_db import TEST_JWT_SECRET, TEST_SUPABASE_UID, make_test_jwt, make_expired_jwt


# ─── JWT Verification Unit Tests ─────────────────────────────────────────


class TestJWTVerification:
    """Test the JWT verification service directly (no HTTP, no DB)."""

    def test_valid_jwt(self):
        """A properly signed JWT with correct claims should verify."""
        token = make_test_jwt()
        claims = verify_supabase_jwt(token)
        assert claims["sub"] == TEST_SUPABASE_UID
        assert claims["email"] == "testuser@insightgenius.io"
        assert claims["aud"] == "authenticated"

    def test_expired_jwt(self):
        """An expired JWT should be rejected."""
        token = make_expired_jwt()
        with pytest.raises(JWTVerificationError, match="expired"):
            verify_supabase_jwt(token)

    def test_wrong_audience(self):
        """A JWT with wrong audience should be rejected."""
        token = make_test_jwt(aud="wrong-audience")
        with pytest.raises(JWTVerificationError, match="audience"):
            verify_supabase_jwt(token)

    def test_missing_sub(self):
        """A JWT without 'sub' claim should be rejected."""
        payload = {
            "email": "test@test.com",
            "aud": "authenticated",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")
        with pytest.raises(JWTVerificationError):
            verify_supabase_jwt(token)

    def test_wrong_secret(self):
        """A JWT signed with wrong secret should be rejected."""
        payload = {
            "sub": "some-uid",
            "aud": "authenticated",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
        with pytest.raises(JWTVerificationError):
            verify_supabase_jwt(token)

    def test_garbage_token(self):
        """A completely invalid token string should be rejected."""
        with pytest.raises(JWTVerificationError):
            verify_supabase_jwt("not.a.jwt")

    def test_empty_token(self):
        """An empty token should be rejected."""
        with pytest.raises(JWTVerificationError):
            verify_supabase_jwt("")


# ─── Auth Dispatch Tests (via HTTP) ──────────────────────────────────────


class TestAuthDispatch:
    """Test that the unified auth dispatches API keys vs JWTs correctly."""

    def test_api_key_still_works(self, client, auth_headers):
        """Existing API key auth continues working on existing endpoints."""
        response = client.get("/v1/health", headers=auth_headers)
        # Health doesn't require auth, but shouldn't break with auth headers
        assert response.status_code == 200

    def test_api_key_on_metadata(self, client, auth_headers, test_sav_bytes):
        """API key auth works on metadata endpoint (existing behavior)."""
        response = client.post(
            "/v1/metadata",
            headers=auth_headers,
            files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        )
        assert response.status_code == 200

    def test_no_auth_header_rejected(self, client):
        """Request without auth header is rejected."""
        response = client.post("/v1/metadata")
        assert response.status_code in (401, 422)  # 401 unauthorized or 422 missing file

    def test_invalid_bearer_format(self, client):
        """Non-Bearer auth is rejected on API key endpoints."""
        response = client.post(
            "/v1/metadata",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
            files={"file": ("test.sav", b"dummy", "application/octet-stream")},
        )
        assert response.status_code == 401


# ─── AuthContext Dataclass Tests ─────────────────────────────────────────


class TestAuthContext:
    """Test the AuthContext dataclass."""

    def test_auth_context_creation(self):
        from auth_unified import AuthContext
        ctx = AuthContext(
            user_id="test-123",
            auth_method="api_key",
            plan="pro",
            scopes=["metadata", "process"],
        )
        assert ctx.user_id == "test-123"
        assert ctx.auth_method == "api_key"
        assert ctx.plan == "pro"
        assert ctx.db_user is None

    def test_is_api_key_detection(self):
        from auth_unified import _is_api_key
        assert _is_api_key("sk_live_abc123") is True
        assert _is_api_key("sk_test_abc123") is True
        assert _is_api_key("eyJhbGciOiJIUzI1NiJ9.xxx") is False
        assert _is_api_key("random_string") is False
