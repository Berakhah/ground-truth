# tests/stats/test_sequential.py
import math
import random
from pathlib import Path

import pytest

from ground_truth.stats.sequential import (
    C_OBF_13_LOOKS,
    LOOKS_PER_QUARTER,
    evaluate_look,
    obrien_fleming_boundary,
    spent_alpha,
)

PLAN = Path(__file__).resolve().parents[2] / "docs" / "analysis-plan.md"


def test_looks_per_quarter_matches_the_pre_registered_plan():
    assert str(LOOKS_PER_QUARTER) in PLAN.read_text(encoding="utf-8")


def test_early_boundaries_are_stricter_than_late_ones():
    assert obrien_fleming_boundary(1, 13) > obrien_fleming_boundary(13, 13)


def test_final_boundary_is_near_the_fixed_sample_critical_value():
    assert obrien_fleming_boundary(13, 13) == pytest.approx(1.96, abs=0.15)


def test_alpha_spent_is_monotone_and_totals_alpha():
    spent = [spent_alpha(k, 13) for k in range(1, 14)]
    assert spent == sorted(spent)
    assert spent[-1] == pytest.approx(0.05, abs=1e-9)


def test_look_out_of_range_raises():
    with pytest.raises(ValueError):
        obrien_fleming_boundary(0, 13)
    with pytest.raises(ValueError):
        obrien_fleming_boundary(14, 13)


def test_result_states_the_test_used():
    result = evaluate_look(4.5, look=2, total_looks=13)
    assert "O'Brien-Fleming" in result.statement
    assert "look 2 of 13" in result.statement


def test_rejection_does_not_publish_the_lan_demets_spend_as_this_boundarys_spend():
    """The boundary is fixed-C classic O'Brien-Fleming, not the Lan-DeMets spending function,
    so `spent_alpha` is not what this procedure has spent: at look 4 the true cumulative
    crossing probability of C/sqrt(t) is ~0.00017 (2M-path Monte Carlo, stats review
    2026-09-27) against Lan-DeMets' 0.00041. The alert must state the guarantee the boundary
    was calibrated to carry, not a figure from a different procedure."""
    result = evaluate_look(4.5, look=4, total_looks=13)
    assert result.reject
    assert f"{spent_alpha(4, 13):.4f}" not in result.statement
    assert "alpha spent" not in result.statement
    assert "family-wise type-I error of 0.05 across the 13-look pre-registered calendar" in (
        result.statement
    )


def test_a_null_result_is_not_reported_as_no_change():
    result = evaluate_look(0.2, look=2, total_looks=13)
    assert not result.reject
    assert "no change was detected" in result.statement
    assert "does not mean no change occurred" in result.statement


def _brownian_z(rng: random.Random, k_total: int) -> list[float]:
    """Z_k = B(t_k)/sqrt(t_k): what sequential monitoring actually produces.

    Successive looks read the SAME accumulating data, so corr(Z_j, Z_k) = sqrt(t_j/t_k).
    Both tests below drew 13 INDEPENDENT normals until 2026-08-29, which is a different
    process entirely -- it reported 0.179 for a procedure whose true error is 0.072, and
    0.487 for a naive threshold whose true error is 0.215. See audit B3.
    """
    b, out = 0.0, []
    for k in range(1, k_total + 1):
        b += rng.gauss(0, math.sqrt(1.0 / k_total))
        out.append(b / math.sqrt(k / k_total))
    return out


@pytest.mark.slow
def test_sequential_controls_type_i_under_null():
    rng, trials = random.Random(0), 20_000
    rejected = sum(
        any(
            evaluate_look(z, look=k, total_looks=13).reject
            for k, z in enumerate(_brownian_z(rng, 13), start=1)
        )
        for _ in range(trials)
    )
    rate = rejected / trials
    assert rate <= 0.055, f"family-wise type I error {rate:.4f} exceeds nominal 0.05"  # noqa: PLR2004


@pytest.mark.slow
def test_calibrated_constant_controls_alpha():
    """The committed C_OBF_13_LOOKS is a calibrated constant, so its calibration is its test."""
    rng, trials = random.Random(11), 20_000
    rate = (
        sum(
            any(
                abs(z) > C_OBF_13_LOOKS / math.sqrt(k / 13)
                for k, z in enumerate(_brownian_z(rng, 13), start=1)
            )
            for _ in range(trials)
        )
        / trials
    )
    assert 0.043 <= rate <= 0.057, (  # noqa: PLR2004
        f"C = {C_OBF_13_LOOKS} yields alpha = {rate:.4f}, not 0.05"
    )


@pytest.mark.slow
def test_fixed_threshold_inflates_alpha():
    rng, trials = random.Random(0), 20_000
    rate = (
        sum(
            any(abs(z) > 1.96 for z in _brownian_z(rng, 13))  # noqa: PLR2004
            for _ in range(trials)
        )
        / trials
    )
    assert 0.18 <= rate <= 0.25, (  # noqa: PLR2004
        f"a naive per-look threshold rejects {rate:.3f} of null trajectories — this is why "
        "the regression watch uses alpha spending, and THIS number goes on the methodology page. "
        "The independent-draw version of this simulation reports ~0.487, which is not a property "
        "of sequential monitoring and must never be published."
    )
