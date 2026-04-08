"""Test fixtures for database-dependent features (Phase 1+).

Uses SQLite in-memory for fast, isolated tests.
These fixtures are automatically discovered by pytest alongside conftest.py.
"""

import os
import pytest
import jwt
import time

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

# Set a test JWT secret BEFORE importing app modules
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-for-testing-only-32chars!")

# Use a sync SQLite for simple model tests (no async needed for unit tests)
TEST_DB_URL = "sqlite:///./test_quantipro.db"

# ─── JWT helpers ─────────────────────────────────────────────────────────

TEST_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]
TEST_SUPABASE_UID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_EMAIL = "testuser@insightgenius.io"


def make_test_jwt(
    sub: str = TEST_SUPABASE_UID,
    email: str = TEST_USER_EMAIL,
    exp_offset: int = 3600,
    aud: str = "authenticated",
) -> str:
    """Generate a valid Supabase-style JWT for testing."""
    payload = {
        "sub": sub,
        "email": email,
        "aud": aud,
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset,
        "user_metadata": {"name": "Test User"},
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def make_expired_jwt() -> str:
    """Generate an expired JWT."""
    return make_test_jwt(exp_offset=-3600)


@pytest.fixture
def test_jwt():
    """A valid Supabase JWT token for testing."""
    return make_test_jwt()


@pytest.fixture
def test_jwt_headers():
    """Auth headers with a valid Supabase JWT."""
    return {"Authorization": f"Bearer {make_test_jwt()}"}


@pytest.fixture
def expired_jwt_headers():
    """Auth headers with an expired JWT."""
    return {"Authorization": f"Bearer {make_expired_jwt()}"}
