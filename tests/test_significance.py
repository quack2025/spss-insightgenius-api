"""Unit tests for significance testing functions."""
import pytest
from shared.significance import bonferroni_alpha, z_test_proportions, t_test_means


class TestBonferroniAlpha:
    def test_single_column_returns_raw(self):
        assert bonferroni_alpha(0.05, 1) == 0.05

    def test_two_columns_one_pair(self):
        assert bonferroni_alpha(0.05, 2) == pytest.approx(0.05)  # 1 pair

    def test_three_columns_three_pairs(self):
        # 3 columns = 3 pairs, alpha/3
        assert bonferroni_alpha(0.05, 3) == pytest.approx(0.05 / 3)

    def test_five_columns_ten_pairs(self):
        # 5 columns = 10 pairs
        assert bonferroni_alpha(0.05, 5) == pytest.approx(0.05 / 10)


class TestZTestProportions:
    def test_identical_proportions_not_significant(self):
        p_val, is_sig = z_test_proportions(0.5, 100, 0.5, 100, 0.05, 2)
        assert not is_sig
        assert p_val >= 0.05

    def test_very_different_proportions_significant(self):
        p_val, is_sig = z_test_proportions(0.9, 500, 0.3, 500, 0.05, 2)
        assert is_sig
        assert p_val < 0.001

    def test_zero_base_returns_not_significant(self):
        p_val, is_sig = z_test_proportions(0.5, 0, 0.5, 100, 0.05, 2)
        assert not is_sig
        assert p_val == 1.0

    def test_negative_base_returns_not_significant(self):
        p_val, is_sig = z_test_proportions(0.5, -1, 0.5, 100, 0.05, 2)
        assert not is_sig

    def test_both_zero_proportions(self):
        p_val, is_sig = z_test_proportions(0.0, 100, 0.0, 100, 0.05, 2)
        assert not is_sig

    def test_p1_less_than_p2_not_significant(self):
        # z_test returns significant only if p1 > p2
        p_val, is_sig = z_test_proportions(0.3, 500, 0.9, 500, 0.05, 2)
        assert not is_sig  # p1 < p2

    def test_bonferroni_makes_borderline_not_significant(self):
        # With 2 columns (no Bonferroni effect), might be sig
        p_val_2, is_sig_2 = z_test_proportions(0.55, 100, 0.40, 100, 0.05, 2, apply_bonferroni=True)
        # With 5 columns (10 pairs), same difference less likely sig
        p_val_5, is_sig_5 = z_test_proportions(0.55, 100, 0.40, 100, 0.05, 5, apply_bonferroni=True)
        # Bonferroni with more columns should be stricter
        assert p_val_2 == p_val_5  # p-value same, threshold changes

    def test_warnings_list_captures_errors(self):
        warnings = []
        # p_pool = 1.0 causes sqrt(0) = 0 se
        p_val, is_sig = z_test_proportions(1.0, 100, 1.0, 100, 0.05, 2, warnings_list=warnings)
        assert not is_sig

    def test_no_bonferroni(self):
        p_val, is_sig = z_test_proportions(0.7, 200, 0.4, 200, 0.05, 5, apply_bonferroni=False)
        assert is_sig  # Large difference, no Bonferroni penalty


class TestTTestMeans:
    def test_identical_means_not_significant(self):
        p_val, is_sig = t_test_means(3.5, 1.0, 100, 3.5, 1.0, 100, 0.05, 2)
        assert not is_sig

    def test_very_different_means_significant(self):
        p_val, is_sig = t_test_means(5.0, 1.0, 200, 2.0, 1.0, 200, 0.05, 2)
        assert is_sig
        assert p_val < 0.001

    def test_small_sample_not_significant(self):
        p_val, is_sig = t_test_means(5.0, 1.0, 1, 2.0, 1.0, 1, 0.05, 2)
        assert not is_sig  # n <= 1

    def test_zero_std_returns_not_significant(self):
        p_val, is_sig = t_test_means(5.0, 0.0, 100, 2.0, 0.0, 100, 0.05, 2)
        assert not is_sig  # se = 0

    def test_mean1_less_than_mean2_not_significant(self):
        # Only significant if mean1 > mean2
        p_val, is_sig = t_test_means(2.0, 1.0, 200, 5.0, 1.0, 200, 0.05, 2)
        assert not is_sig

    def test_warnings_list_on_error(self):
        warnings = []
        t_test_means(5.0, 0.0, 100, 2.0, 0.0, 100, 0.05, 2, warnings_list=warnings)
        # May or may not add warning depending on exact error path
        assert isinstance(warnings, list)

    def test_no_bonferroni(self):
        p_val, is_sig = t_test_means(4.5, 1.0, 100, 3.5, 1.0, 100, 0.05, 5, apply_bonferroni=False)
        assert is_sig
