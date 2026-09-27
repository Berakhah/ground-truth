# tests/stats/test_sequential.py
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import norm

from ground_truth.stats.sequential import (
    FAMILY_ALPHA,
    LOOKS_PER_QUARTER,
    PER_LOOK_BOUNDARY_13_LOOKS,
    evaluate_look,
    per_look_alpha,
    per_look_boundary,
    sidak_adjust,
)

PLAN = Path(__file__).resolve().parents[2] / "docs" / "analysis-plan.md"


def test_looks_per_quarter_matches_the_pre_registered_plan():
    assert str(LOOKS_PER_QUARTER) in PLAN.read_text(encoding="utf-8")


def test_per_look_alpha_is_the_sidak_share_of_the_family_alpha():
    """13 independent tests at alpha_look have family-wise error exactly 1-(1-alpha_look)^13."""
    a = per_look_alpha(LOOKS_PER_QUARTER)
    assert 1 - (1 - a) ** LOOKS_PER_QUARTER == pytest.approx(FAMILY_ALPHA, abs=1e-15)
    assert a == pytest.approx(0.003938, abs=5e-7)


def test_boundary_is_the_two_sided_critical_value_of_the_per_look_alpha():
    expected = float(norm.ppf(1 - per_look_alpha(LOOKS_PER_QUARTER) / 2))
    assert per_look_boundary(LOOKS_PER_QUARTER) == pytest.approx(expected, abs=1e-12)


def test_committed_boundary_constant_matches_its_closed_form_and_the_plan():
    """The published constant is a rounding of the closed form, and the plan states it."""
    assert round(per_look_boundary(LOOKS_PER_QUARTER), 4) == PER_LOOK_BOUNDARY_13_LOOKS
    assert PER_LOOK_BOUNDARY_13_LOOKS == 2.8831  # noqa: PLR2004
    assert "2.8831" in PLAN.read_text(encoding="utf-8")


def test_boundary_is_the_same_at_every_look():
    """Stats review 2026-09-27, finding 1: the O'Brien-Fleming boundary was 7.58 at look 1 of
    13, so a model swapped early in the quarter went unseen. Every look now has one boundary."""
    results = [evaluate_look(3.0, look=k, total_looks=13) for k in range(1, 14)]
    assert {r.boundary for r in results} == {per_look_boundary(13)}
    assert all(r.reject for r in results), "|z| = 3.0 must be detectable at look 1 as at look 13"


def test_sidak_adjustment_matches_a_worked_example():
    # p = 0.001 over 13 looks: 1 - 0.999^13 = 0.0129222853 (exact rational arithmetic)
    assert sidak_adjust(0.001, 13) == pytest.approx(0.0129222853, abs=1e-10)
    assert sidak_adjust(0.0, 13) == 0.0
    assert sidak_adjust(1.0, 13) == 1.0


def test_sidak_adjusted_p_crosses_alpha_exactly_at_the_boundary():
    b = per_look_boundary(13)
    p_at_boundary = 2 * (1 - float(norm.cdf(b)))
    assert sidak_adjust(p_at_boundary, 13) == pytest.approx(FAMILY_ALPHA, abs=1e-12)


def test_look_out_of_range_raises():
    with pytest.raises(ValueError):
        evaluate_look(1.0, look=0, total_looks=13)
    with pytest.raises(ValueError):
        evaluate_look(1.0, look=14, total_looks=13)


def test_result_states_the_test_the_boundary_and_both_p_values():
    result = evaluate_look(4.5, look=2, total_looks=13)
    assert result.reject
    assert "Šidák" in result.statement
    assert "look 2 of 13" in result.statement
    assert "2.883" in result.statement
    assert f"{result.p_value:.2g}" in result.statement
    assert f"{result.adjusted_p:.2g}" in result.statement
    assert "family-wise type-I error of 0.05 across the 13-look calendar" in result.statement
    assert "O'Brien-Fleming" not in result.statement
    assert "alpha spent" not in result.statement


def test_a_null_result_is_not_reported_as_no_change():
    result = evaluate_look(0.2, look=2, total_looks=13)
    assert not result.reject
    assert "no change was detected" in result.statement
    assert "does not mean no change occurred" in result.statement


def _shared_baseline_null_z(rng: np.random.Generator, trials: int, rho: float) -> np.ndarray:
    """z_k = (C_k - B) / sd for 13 looks under the null, where each look's sweep C_k is
    independent and every look is compared with the same baseline estimate B.

    rho = Var(B) / (Var(B) + Var(C)) is the correlation between any two looks' z. It is 0.5
    when the baseline sweep is the same size as a look, which is the registered design, and 0
    in the limit of a noiseless baseline. The looks are NOT the correlated Brownian process of
    the v1 cumulative design (corr = sqrt(t_j/t_k)): each look is tested on its own sweep.
    """
    looks = rng.standard_normal((trials, LOOKS_PER_QUARTER))
    baseline = rng.standard_normal((trials, 1))
    return np.asarray(np.sqrt(1 - rho) * looks - np.sqrt(rho) * baseline)


@pytest.mark.slow
@pytest.mark.parametrize("rho", [0.0, 0.2, 0.5, 0.8])
def test_family_wise_error_stays_within_alpha_under_a_shared_baseline(rho):
    """The null simulation asserts the any-look false-alarm rate across the whole 13-look
    quarter, not the per-look rate. Šidák's inequality bounds it by 0.05 at every correlation;
    at rho = 0 it is exactly 0.05, so the tolerance is the Monte Carlo error of 400,000 trials
    (sd ~0.00034, tolerance ~4.4 sd), not slack."""
    rng = np.random.default_rng(20260928)
    z = _shared_baseline_null_z(rng, 400_000, rho)
    rate = float((np.abs(z) > per_look_boundary(LOOKS_PER_QUARTER)).any(axis=1).mean())
    # Seeded, so exact: these are the figures the plan and methodology publish (rho 0 and 0.5).
    assert round(rate, 4) == {0.0: 0.0501, 0.2: 0.0479, 0.5: 0.0381, 0.8: 0.0218}[rho]
    assert rate <= FAMILY_ALPHA + 0.0015, f"rho={rho}: family-wise error {rate:.4f} > 0.05"
    if rho == 0.0:
        assert rate == pytest.approx(FAMILY_ALPHA, abs=0.0015)


@pytest.mark.slow
def test_family_wise_error_through_evaluate_look_itself():
    """The same null, run through the function the regression watch calls rather than a
    re-derivation of its boundary. Fewer trials because it is a Python loop (sd ~0.0014)."""
    rng = np.random.default_rng(7)
    z = _shared_baseline_null_z(rng, 20_000, 0.5)
    flagged = [
        any(evaluate_look(float(zk), look=k, total_looks=13).reject for k, zk in enumerate(row, 1))
        for row in z
    ]
    rate = sum(flagged) / len(flagged)
    assert rate <= 0.055, f"family-wise error {rate:.4f} exceeds 0.05"  # noqa: PLR2004


@pytest.mark.slow
def test_fixed_threshold_inflates_alpha():
    """What the per-look design would do without the Šidák correction: |z| > 1.96 at each of 13
    looks against a shared, look-sized baseline falsely flags a third of null quarters (0.3343
    at this seed). THIS is the figure on the methodology page for the v2 design; v1's 0.2119
    was for pooled looks and describes a procedure no longer in use."""
    rng = np.random.default_rng(0)
    z = _shared_baseline_null_z(rng, 400_000, 0.5)
    rate = float((np.abs(z) > 1.96).any(axis=1).mean())  # noqa: PLR2004
    assert round(rate, 4) == 0.3343, "the methodology page publishes this figure as 0.334"  # noqa: PLR2004
    assert 0.32 <= rate <= 0.35, f"naive per-look threshold rejects {rate:.4f} of null quarters"  # noqa: PLR2004


def test_extreme_z_keeps_a_nonzero_p_value():
    """Code review 2026-09-27 #3: 2 * (1 - cdf(|z|)) is exactly 0 above |z| ~ 8.3, so a large
    drift published "p = 0" -- a certainty no test has."""
    result = evaluate_look(10.0, look=1, total_looks=13)
    assert 0 < result.p_value < 1e-20  # noqa: PLR2004
    assert 0 < result.adjusted_p < 1e-18  # noqa: PLR2004
    assert "p = 0," not in result.statement and "p = 0;" not in result.statement


def test_sidak_adjust_is_accurate_for_tiny_p():
    assert sidak_adjust(1e-30, 13) == pytest.approx(1.3e-29, rel=1e-9)


def test_only_the_pre_registered_calendar_is_accepted():
    """The plan registers 13 looks at family alpha 0.05. Any other calendar is an unregistered
    change of method, so it raises rather than quietly using a different boundary."""
    with pytest.raises(ValueError, match="pre-registered"):
        evaluate_look(1.0, look=14, total_looks=26)
    with pytest.raises(ValueError, match="pre-registered"):
        evaluate_look(1.0, look=2, total_looks=13, alpha=0.1)


def test_result_carries_the_per_look_alpha_it_was_tested_at():
    assert evaluate_look(1.0, look=2, total_looks=13).alpha_look == per_look_alpha(13)


def test_published_simulation_figures_appear_in_the_plan_and_methodology():
    """The slow tests below pin these figures to the code; this pins them to the documents."""
    methodology = (PLAN.parent / "methodology.md").read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    for figure in ("0.0501", "0.0381"):
        assert figure in plan and figure in methodology, figure
    assert "0.334" in methodology
