import pytest
from scipy.stats import norm

from ground_truth.stats.mde import (
    describe_mde,
    describe_mde_two_sample,
    mde_paired_binary,
    mde_two_sample,
)


def test_matches_closed_form_for_a_single_comparison():
    # McNemar normal approximation: delta = (z_{alpha/2} + z_{power}) * sqrt(disc / n)
    # n=180, disc=0.10 -> (1.959964 + 0.841621) * sqrt(0.10/180)
    assert mde_paired_binary(180, 0.10) == pytest.approx(0.066033, abs=5e-5)


def test_mde_falls_as_n_rises():
    assert mde_paired_binary(300, 0.10) < mde_paired_binary(180, 0.10)


def test_mde_rises_with_more_comparisons():
    assert mde_paired_binary(180, 0.10, n_comparisons=48) > mde_paired_binary(180, 0.10)


def test_mde_rises_with_discordance():
    assert mde_paired_binary(180, 0.30) > mde_paired_binary(180, 0.10)


def test_zero_items_raises():
    with pytest.raises(ValueError):
        mde_paired_binary(0, 0.10)


def test_discordance_out_of_range_raises():
    with pytest.raises(ValueError):
        mde_paired_binary(180, 0.0)
    with pytest.raises(ValueError):
        mde_paired_binary(180, 1.5)


def test_description_states_n_the_correction_and_the_null_caveat():
    text = describe_mde(180, 0.10, n_comparisons=48)
    assert "180" in text and "Bonferroni" in text and "48" in text
    assert "not that none exists" in text


def test_two_sample_mde_matches_the_z_test_it_describes():
    """The regression watch decides with z = diff / sqrt(se_b^2 + se_c^2); its MDE must be for
    that test, not the paired McNemar test `mde_paired_binary` describes (code review
    2026-09-27 #3: the paired formula claimed 10.2 pp where the real test needs ~13.6 pp)."""
    se = 0.03
    expected = (norm.ppf(1 - 0.01 / (2 * 2)) + norm.ppf(0.8)) * se
    assert mde_two_sample(se, alpha=0.01, n_comparisons=2) == pytest.approx(expected, rel=1e-12)


def test_two_sample_mde_rejects_a_non_positive_standard_error():
    with pytest.raises(ValueError, match="standard error"):
        mde_two_sample(0.0)


def test_two_sample_description_states_both_ns_the_correction_and_the_null_caveat():
    text = describe_mde_two_sample(150, 140, 0.03, alpha=0.003938, n_comparisons=2)
    assert "At n=150 baseline and 140 current items" in text
    assert "alpha=0.003938" in text
    assert "Bonferroni-corrected across 2 comparisons" in text
    assert "not that none exists" in text
