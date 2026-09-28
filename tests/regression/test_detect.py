# tests/regression/test_detect.py
import math
import random

import pytest
from scipy.stats import norm

from ground_truth.regression.detect import detect_drift
from ground_truth.stats.correction import Comparison, benjamini_hochberg
from ground_truth.stats.mde import mde_two_sample
from ground_truth.stats.sequential import P_DISPLAY_FLOOR, format_p, per_look_alpha, sidak_adjust


def obs(n: int, p: float, seed: int) -> list[tuple[str, bool]]:
    rng = random.Random(seed)
    return [(f"i{i}", rng.random() < p) for i in range(n)]


def obs_with_ids(ids: list[str], p: float, seed: int) -> list[tuple[str, bool]]:
    rng = random.Random(seed)
    return [(i, rng.random() < p) for i in ids]


def test_no_drift_produces_no_detection():
    base = {("slot-a", "money"): obs(180, 0.90, 1)}
    curr = {("slot-a", "money"): obs(180, 0.90, 2)}
    alerts = detect_drift(base, curr, look=5, total_looks=13, seed=1)
    assert not any(a.detected for a in alerts)


def test_large_drift_is_detected():
    base = {("slot-a", "money"): obs(180, 0.95, 1)}
    curr = {("slot-a", "money"): obs(180, 0.55, 2)}
    alerts = detect_drift(base, curr, look=5, total_looks=13, seed=1)
    assert any(a.detected for a in alerts)


def test_alert_states_its_test():
    base = {("slot-a", "money"): obs(180, 0.95, 1)}
    curr = {("slot-a", "money"): obs(180, 0.55, 2)}
    alerts = detect_drift(base, curr, look=5, total_looks=13, seed=1)
    alert = next(a for a in alerts if a.detected)
    assert "Šidák" in alert.statement
    assert "Benjamini-Hochberg" in alert.statement
    assert "look 5 of 13" in alert.statement
    assert "O'Brien-Fleming" not in alert.statement, (
        "code review 2026-09-27 #2, finding 1: detect_drift wrote its own alert text and kept "
        "the retired O'Brien-Fleming wording after sequential.py's statement was corrected"
    )
    assert "boundary of 2.883" in alert.statement
    assert "Šidák-adjusted p" in alert.statement


def test_alert_carries_both_intervals():
    base = {("slot-a", "money"): obs(180, 0.95, 1)}
    curr = {("slot-a", "money"): obs(180, 0.55, 2)}
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1)[0]
    assert alert.baseline.n == 180 and alert.current.n == 180  # noqa: PLR2004


def test_a_null_result_reports_undetectable_not_absent():
    base = {("slot-a", "money"): obs(180, 0.90, 1)}
    curr = {("slot-a", "money"): obs(180, 0.90, 2)}
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1)[0]
    assert not alert.detected
    assert "percentage points" in alert.statement
    assert "not that none exists" in alert.statement, (
        "a null result must state what the sample could not see"
    )


def test_multiplicity_correction_is_applied_across_all_comparisons():
    base = {(f"slot-{i}", "money"): obs(180, 0.90, i) for i in range(12)}
    curr = {(f"slot-{i}", "money"): obs(180, 0.90, 100 + i) for i in range(12)}
    alerts = detect_drift(base, curr, look=5, total_looks=13, seed=1)
    assert len(alerts) == 12  # noqa: PLR2004
    assert sum(a.detected for a in alerts) == 0, (
        "12 null comparisons should not produce a detection"
    )


def test_missing_baseline_key_raises_rather_than_silently_skipping():
    with pytest.raises(KeyError):
        detect_drift({}, {("slot-a", "money"): obs(10, 0.9, 1)}, look=1, total_looks=13, seed=1)


def test_only_this_looks_sweep_is_tested_not_a_pooled_history():
    """Plan v2: each look is tested on its own sweep. The v1 signature took one dict per look
    and pooled them; passing that shape now is a mistake, and it fails loudly."""
    base = {("slot-a", "money"): obs(180, 0.90, 1)}
    curr = {("slot-a", "money"): obs(180, 0.90, 2)}
    with pytest.raises(TypeError, match="this look"):
        detect_drift(base, [curr], look=5, total_looks=13, seed=1)  # type: ignore[arg-type]


@pytest.mark.parametrize("look", [1, 10])
def test_a_model_swap_is_seen_at_full_strength_whenever_it_happens(look):
    """Code review 2026-09-27 #2, finding 2: pooled across the quarter, a model degraded from
    0.95 to 0.55 at look 10 was diluted by nine looks of the old model, and at look 1 the
    O'Brien-Fleming boundary was 7.58. Tested on this look's sweep, both are detected."""
    base = {("slot-a", "money"): obs(180, 0.95, 1)}
    curr = {("slot-a", "money"): obs(180, 0.55, 2)}
    alert = detect_drift(base, curr, look=look, total_looks=13, seed=1)[0]
    assert alert.detected
    assert f"look {look} of 13" in alert.statement


def test_look_out_of_range_raises_even_with_nothing_to_test():
    """Finding 8: look=0 with no data returned [] silently instead of raising."""
    with pytest.raises(ValueError, match="look"):
        detect_drift({}, {}, look=0, total_looks=13, seed=1)


def test_corrections_stack_sidak_across_looks_then_bh_across_cells():
    """Plan v2: each cell's per-look p is Šidák-adjusted across the 13 looks, then BH is applied
    across cells. Re-derive the published adjusted p from each alert's own z."""
    base = {(f"slot-{i}", "money"): obs(180, 0.92, i) for i in range(4)}
    curr = {
        (f"slot-{i}", "money"): obs(180, p, 50 + i) for i, p in enumerate([0.92, 0.9, 0.8, 0.6])
    }
    alerts = detect_drift(base, curr, look=3, total_looks=13, seed=1)
    sidak = [sidak_adjust(2 * (1 - float(norm.cdf(abs(a.z)))), 13) for a in alerts]
    expected = benjamini_hochberg(
        [Comparison(label=str(i), p_value=p) for i, p in enumerate(sidak)]
    )
    for alert, corrected in zip(alerts, expected, strict=True):
        assert alert.adjusted_p == pytest.approx(corrected.adjusted_p, rel=1e-12)
        assert alert.detected is corrected.significant


def test_the_mde_is_for_one_look_at_the_per_look_alpha_across_the_family():
    """Condition 1 of the v2 change: a null result publishes what one look can see, at the
    per-look alpha, Bonferroni-corrected across the cells in the family (plan, "Minimum
    detectable effect"). Before, it used alpha = 0.05 and a family of one."""
    base = {(f"slot-{i}", "money"): obs(180, 0.90, i) for i in range(3)}
    curr = {(f"slot-{i}", "money"): obs(180, 0.90, 10 + i) for i in range(3)}
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1)[0]
    assert not alert.detected
    assert "Bonferroni-corrected across 3 comparisons" in alert.statement
    assert f"alpha={per_look_alpha(13):.4g}" in alert.statement


def test_the_mde_is_computed_for_the_z_test_that_decides_detection():
    """Code review 2026-09-27 #3: the MDE sentence used the paired McNemar formula while
    detection is an unpaired z on the two intervals' standard errors, so it overstated what a
    null look could see. The MDE now uses the same standard error as the test."""
    base = {("slot-a", "money"): obs(150, 0.90, 1)}
    curr = {("slot-a", "money"): obs(150, 0.90, 2)}
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1)[0]
    assert not alert.detected
    z_95 = norm.ppf(0.975)
    se = math.hypot(
        (alert.baseline.high - alert.baseline.low) / (2 * z_95),
        (alert.current.high - alert.current.low) / (2 * z_95),
    )
    expected = mde_two_sample(se, alpha=per_look_alpha(13), n_comparisons=1)
    assert f"{expected * 100:.1f} percentage points" in alert.statement
    assert "discordance" not in alert.statement


def test_a_cell_with_no_observations_is_refused_by_name():
    """Code review 2026-09-27 #3: an empty cell crashed the whole look inside the bootstrap.
    A cell that ran nothing is the caller's to leave out; the error says which one."""
    base = {("slot-a", "money"): obs(50, 0.9, 1), ("slot-b", "date"): obs(50, 0.9, 2)}
    curr = {("slot-a", "money"): [], ("slot-b", "date"): obs(50, 0.9, 3)}
    with pytest.raises(ValueError, match="slot-a/money"):
        detect_drift(base, curr, look=2, total_looks=13, seed=1)


def test_an_unregistered_calendar_is_refused():
    base = {("slot-a", "money"): obs(50, 0.9, 1)}
    curr = {("slot-a", "money"): obs(50, 0.9, 2)}
    with pytest.raises(ValueError, match="pre-registered"):
        detect_drift(base, curr, look=14, total_looks=26, seed=1)


def test_constant_score_side_does_not_crash():
    # A constant-score side (every item correct) drives stats/bootstrap.py's degenerate/
    # zero-width-interval branch (point == 1.0 -> Clopper-Pearson exact bound, not a std-based
    # width). detect_drift's z statistic divides by each side's SE derived from interval width --
    # this confirms that coupling actually holds (no ZeroDivisionError) rather than relying on it
    # silently.
    base = {("slot-a", "money"): [(f"i{i}", True) for i in range(50)]}
    curr = {("slot-a", "money"): obs(50, 0.90, 2)}
    alerts = detect_drift(base, curr, look=5, total_looks=13, seed=1)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.baseline.point == 1.0
    assert isinstance(alert.detected, bool)
    assert alert.statement


def test_per_key_attribution_is_positional_not_label_based():
    # Two comparisons in one call, one drifting and one not. If the BH-adjusted results were
    # ever re-matched to keys by a synthesized label string instead of by position, a collision
    # or reordering would misattribute significance across keys -- confirm each key's own result
    # actually lines up with its own data.
    base = {
        ("slot-a", "money"): obs(180, 0.95, 1),
        ("slot-b", "money"): obs(180, 0.90, 3),
    }
    curr = {
        ("slot-a", "money"): obs(180, 0.55, 2),
        ("slot-b", "money"): obs(180, 0.90, 4),
    }
    alerts = {
        (a.slot, a.field_type): a for a in detect_drift(base, curr, look=5, total_looks=13, seed=1)
    }
    assert alerts[("slot-a", "money")].detected
    assert not alerts[("slot-b", "money")].detected


def test_cohort_restriction_excludes_rotated_items_and_says_so():
    base = {("slot-a", "money"): obs(100, 0.90, 1)}
    curr = {("slot-a", "money"): obs(100, 0.90, 2)}
    cohort = {f"i{i}" for i in range(80)}
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1, cohort=cohort)[0]
    assert alert.baseline.n == 80 and alert.current.n == 80  # noqa: PLR2004
    assert "present in both releases" in alert.statement
    assert "At n=80 baseline and 80 current items" in alert.statement, (
        "the MDE must describe the cohort that was tested"
    )


def test_comparing_across_a_rotation_without_a_cohort_is_refused():
    base = {("slot-a", "money"): obs(100, 0.90, 1)}
    curr = {("slot-a", "money"): obs(100, 0.90, 2)}
    with pytest.raises(ValueError, match="cohort"):
        detect_drift(base, curr, look=5, total_looks=13, seed=1, cross_release=True)


def test_a_large_drift_never_prints_a_p_value_of_zero():
    """Every p-value in the alert is printed to significant figures: `.4f` printed a BH p of
    2e-06 as "0.0000", the same false certainty as the underflowed per-look p."""
    base = {("slot-a", "money"): obs(180, 0.95, 1)}
    curr = {("slot-a", "money"): obs(180, 0.55, 2)}
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1)[0]
    assert alert.detected and alert.adjusted_p > 0
    assert "p = 0.0000" not in alert.statement and "p = 0," not in alert.statement
    assert f"Benjamini-Hochberg adjusted {format_p(alert.adjusted_p)}" in alert.statement


def test_a_collapse_publishes_p_below_the_floor_in_all_three_fields():
    """Code review 2026-09-28 #1, the reproduced case: 180/180 -> 3/180 drove |z| past the range
    where `norm.sf` underflows, and all three p-value fields printed "p = 0"."""
    base = {("slot-a", "money"): [(f"i{i}", True) for i in range(180)]}
    curr = {("slot-a", "money"): [(f"i{i}", i < 3) for i in range(180)]}  # noqa: PLR2004
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1)[0]
    assert alert.detected and alert.adjusted_p > 0
    assert alert.statement.count(f"p < {P_DISPLAY_FLOOR:g}") == 3  # noqa: PLR2004
    assert "p = 0" not in alert.statement


def test_a_cell_emptied_by_the_cohort_filter_is_refused_by_name():
    """Code review 2026-09-28 #3: the empty-cell check ran before the cohort filter, so a cell
    whose current items all rotated out crashed the look inside the bootstrap, unnamed."""
    base = {("slot-a", "money"): obs(50, 0.9, 1), ("slot-b", "date"): obs(50, 0.9, 2)}
    curr = {
        ("slot-a", "money"): obs_with_ids([f"new{i}" for i in range(50)], 0.9, 3),
        ("slot-b", "date"): obs(50, 0.9, 4),
    }
    cohort = {f"i{i}" for i in range(50)}
    with pytest.raises(ValueError, match="slot-a/money"):
        detect_drift(base, curr, look=2, total_looks=13, seed=1, cohort=cohort, cross_release=True)


def test_a_cell_with_an_empty_baseline_is_refused_by_name():
    base = {("slot-a", "money"): [], ("slot-b", "date"): obs(50, 0.9, 2)}
    curr = {("slot-a", "money"): obs(50, 0.9, 3), ("slot-b", "date"): obs(50, 0.9, 4)}
    with pytest.raises(ValueError, match="slot-a/money"):
        detect_drift(base, curr, look=2, total_looks=13, seed=1)


def test_every_empty_cell_is_named_in_one_error():
    base = {("slot-a", "money"): [], ("slot-b", "date"): obs(50, 0.9, 2)}
    curr = {("slot-a", "money"): obs(50, 0.9, 3), ("slot-b", "date"): []}
    with pytest.raises(ValueError, match="baseline of slot-a/money, current of slot-b/date"):
        detect_drift(base, curr, look=2, total_looks=13, seed=1)


def _degrade(monkeypatch, bad_calls: set[int], update: dict[str, float]) -> None:
    import ground_truth.regression.detect as mod  # noqa: PLC0415

    real = mod.cluster_bootstrap_ci
    calls = iter(range(100))

    def degraded(observations, *, seed):  # type: ignore[no-untyped-def]
        interval = real(observations, seed=seed)
        if next(calls) in bad_calls:
            return interval.model_copy(update=update or {"high": interval.low})
        return interval

    monkeypatch.setattr(mod, "cluster_bootstrap_ci", degraded)


TWO_CELLS = (
    {("slot-a", "money"): obs(50, 0.9, 1), ("slot-b", "date"): obs(50, 0.9, 2)},
    {("slot-a", "money"): obs(50, 0.9, 3), ("slot-b", "date"): obs(50, 0.9, 4)},
)


@pytest.mark.parametrize(
    "update", [{"low": float("nan")}, {"high": float("inf")}, {}], ids=["nan", "inf", "zero"]
)
def test_a_cell_whose_z_cannot_be_computed_is_refused_by_name(monkeypatch, update):
    """Re-review 2026-09-28: a NaN bound gave a NaN z that `evaluate_look` refused without a
    cell name; a zero-width pair divided by zero, also unnamed; an infinite bound gave z = 0
    and published a null result. Each is refused, naming the cell."""
    _degrade(monkeypatch, {2, 3}, update)
    with pytest.raises(ValueError, match="slot-b/date") as excinfo:
        detect_drift(*TWO_CELLS, look=2, total_looks=13, seed=1)
    assert "slot-a/money" not in str(excinfo.value)


def test_every_cell_whose_z_cannot_be_computed_is_named_in_one_error(monkeypatch):
    _degrade(monkeypatch, {0, 1, 2, 3}, {"low": float("nan")})
    with pytest.raises(ValueError, match="slot-a/money, slot-b/date"):
        detect_drift(*TWO_CELLS, look=2, total_looks=13, seed=1)
