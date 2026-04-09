"""Shared test fixtures."""

import hashlib
import json
import os
import tempfile

import numpy as np
import pandas as pd
import pyreadstat
import pytest
from fastapi.testclient import TestClient

TEST_KEY = "sk_test_quantipro_test_key_abc123"
TEST_KEY_HASH = hashlib.sha256(TEST_KEY.encode()).hexdigest()

# Configure env BEFORE importing app
os.environ["API_KEYS_JSON"] = json.dumps([
    {
        "key_hash": TEST_KEY_HASH,
        "name": "Test Key",
        "plan": "pro",
        "scopes": ["process", "metadata", "convert", "crosstab", "frequency", "parse_ticket", "tabulate", "auto_analyze", "correlation", "anova", "gap_analysis", "satisfaction_summary"],
    }
])
os.environ["APP_ENV"] = "development"
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-for-testing-only-32chars!")

# Clear settings cache so test env vars take effect
from config import get_settings
get_settings.cache_clear()

from main import app
from auth import init_key_registry
init_key_registry()

# Module-level client (avoids fixture ordering issues)
_client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client():
    return _client


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TEST_KEY}"}


@pytest.fixture(scope="session")
def test_sav_bytes():
    """Generate a small test .sav file with known data."""
    np.random.seed(42)
    n = 100
    df = pd.DataFrame({
        "gender": np.random.choice([1.0, 2.0], size=n),
        "age_group": np.random.choice([1.0, 2.0, 3.0], size=n),
        "satisfaction": np.random.choice([1.0, 2.0, 3.0, 4.0, 5.0], size=n),
        "recommend": np.random.choice([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0], size=n),
        "weight_var": np.random.uniform(0.5, 1.5, size=n).round(2),
    })

    column_labels = {
        "gender": "Gender",
        "age_group": "Age Group",
        "satisfaction": "Overall Satisfaction",
        "recommend": "Likelihood to Recommend (NPS)",
        "weight_var": "Survey Weight",
    }
    variable_value_labels = {
        "gender": {1.0: "Male", 2.0: "Female"},
        "age_group": {1.0: "18-34", 2.0: "35-54", 3.0: "55+"},
        "satisfaction": {1.0: "Very dissatisfied", 2.0: "Dissatisfied", 3.0: "Neutral", 4.0: "Satisfied", 5.0: "Very satisfied"},
    }

    fd, tmp_path = tempfile.mkstemp(suffix=".sav")
    os.close(fd)
    try:
        pyreadstat.write_sav(
            df, tmp_path,
            column_labels=column_labels,
            variable_value_labels=variable_value_labels,
        )
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


@pytest.fixture(scope="session")
def test_sav_bytes_with_mrs():
    """Generate a test .sav file with MRS (multiple response) variables."""
    np.random.seed(99)
    n = 100
    df = pd.DataFrame({
        "gender": np.random.choice([1.0, 2.0], size=n),
        "AWARE_A": np.random.choice([0.0, 1.0], size=n),
        "AWARE_B": np.random.choice([0.0, 1.0], size=n),
        "AWARE_C": np.random.choice([0.0, 1.0], size=n),
    })
    column_labels = {
        "gender": "Gender",
        "AWARE_A": "Awareness: Brand A",
        "AWARE_B": "Awareness: Brand B",
        "AWARE_C": "Awareness: Brand C",
    }
    variable_value_labels = {
        "gender": {1.0: "Male", 2.0: "Female"},
        "AWARE_A": {0.0: "No", 1.0: "Yes"},
        "AWARE_B": {0.0: "No", 1.0: "Yes"},
        "AWARE_C": {0.0: "No", 1.0: "Yes"},
    }
    fd, tmp_path = tempfile.mkstemp(suffix=".sav")
    os.close(fd)
    try:
        pyreadstat.write_sav(
            df, tmp_path,
            column_labels=column_labels,
            variable_value_labels=variable_value_labels,
        )
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)
