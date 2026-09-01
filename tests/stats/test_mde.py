import pytest

from ground_truth.stats.mde import describe_mde, mde_paired_binary


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
