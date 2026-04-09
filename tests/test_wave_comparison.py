"""Tests for wave comparison service."""
import pytest
import pandas as pd
from dataclasses import dataclass
from unittest.mock import MagicMock
from services.wave_comparison import compare_waves


@dataclass
class MockMeta:
    column_names_to_labels: dict
    variable_value_labels: dict


@dataclass
class MockSPSSData:
    df: pd.DataFrame
    meta: MockMeta
    file_name: str = "test.sav"


def _make_wave(data: dict, value_labels: dict = None, col_labels: dict = None) -> MockSPSSData:
    """Helper to create mock SPSSData for wave comparison."""
    df = pd.DataFrame(data)
    meta = MockMeta(
        column_names_to_labels=col_labels or {c: c for c in df.columns},
        variable_value_labels=value_labels or {},
    )
    return MockSPSSData(df=df, meta=meta)


class TestCompareWaves:
    def test_basic_comparison_returns_structure(self):
        wave1 = _make_wave({"Q1": [1, 2, 3, 4, 5] * 20}, {"Q1": {1: "Low", 5: "High"}})
        wave2 = _make_wave({"Q1": [3, 4, 5, 5, 5] * 20}, {"Q1": {1: "Low", 5: "High"}})

        result = compare_waves(wave1, wave2, variables=["Q1"])

        assert result["wave1"]["n_cases"] == 100
        assert result["wave2"]["n_cases"] == 100
        assert result["variables_compared"] == 1
        assert len(result["comparisons"]) == 1
        assert "frequencies" in result["comparisons"][0]
        assert "mean_delta" in result["comparisons"][0]

    def test_auto_detect_shared_variables(self):
        wave1 = _make_wave(
            {"Q1": [1, 2, 3] * 30, "Q2": [4, 5, 6] * 30, "only_w1": [1] * 90},
            {"Q1": {1: "A", 2: "B", 3: "C"}, "Q2": {4: "D", 5: "E", 6: "F"}},
        )
        wave2 = _make_wave(
            {"Q1": [2, 3, 3] * 30, "Q2": [5, 6, 6] * 30, "only_w2": [2] * 90},
            {"Q1": {1: "A", 2: "B", 3: "C"}, "Q2": {4: "D", 5: "E", 6: "F"}},
        )

        result = compare_waves(wave1, wave2)
        assert result["variables_compared"] == 2  # Q1 and Q2, not only_w1/only_w2

    def test_mean_delta_calculated(self):
        wave1 = _make_wave({"Q1": [2.0] * 50}, {"Q1": {1: "L", 2: "M", 3: "H"}})
        wave2 = _make_wave({"Q1": [3.0] * 50}, {"Q1": {1: "L", 2: "M", 3: "H"}})

        result = compare_waves(wave1, wave2, variables=["Q1"])
        comp = result["comparisons"][0]
        assert comp["mean_delta"]["wave1_mean"] == 2.0
        assert comp["mean_delta"]["wave2_mean"] == 3.0
        assert comp["mean_delta"]["delta"] == 1.0
        assert comp["mean_delta"]["direction"] == "up"

    def test_empty_data_in_one_wave(self):
        wave1 = _make_wave({"Q1": [float("nan")] * 50}, {"Q1": {1: "A"}})
        wave2 = _make_wave({"Q1": [1, 2, 3] * 30}, {"Q1": {1: "A", 2: "B", 3: "C"}})

        result = compare_waves(wave1, wave2, variables=["Q1"])
        assert result["comparisons"][0].get("error") == "No valid data in one or both waves"

    def test_variable_not_in_one_wave_skipped(self):
        wave1 = _make_wave({"Q1": [1, 2] * 50}, {"Q1": {1: "A", 2: "B"}})
        wave2 = _make_wave({"Q2": [1, 2] * 50}, {"Q2": {1: "A", 2: "B"}})

        result = compare_waves(wave1, wave2, variables=["Q1"])
        assert result["variables_compared"] == 0  # Q1 not in wave2

    def test_significance_level_passed(self):
        wave1 = _make_wave({"Q1": [1, 2, 3] * 30}, {"Q1": {1: "A", 2: "B", 3: "C"}})
        wave2 = _make_wave({"Q1": [2, 3, 3] * 30}, {"Q1": {1: "A", 2: "B", 3: "C"}})

        result = compare_waves(wave1, wave2, significance_level=0.99)
        assert result["significance_level"] == 0.99

    def test_top_changes_limited_to_10(self):
        # Create many variables
        data = {f"Q{i}": [1, 2] * 50 for i in range(15)}
        vl = {f"Q{i}": {1: "A", 2: "B"} for i in range(15)}
        wave1 = _make_wave(data, vl)
        # Make wave2 very different
        data2 = {f"Q{i}": [2, 2] * 50 for i in range(15)}
        wave2 = _make_wave(data2, vl)

        result = compare_waves(wave1, wave2)
        assert len(result["top_changes"]) <= 10
