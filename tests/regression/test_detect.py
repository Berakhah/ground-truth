# tests/regression/test_detect.py
import random

import pytest

from ground_truth.regression.detect import detect_drift
from ground_truth.stats.mde import describe_mde


def obs(n: int, p: float, seed: int) -> list[tuple[str, bool]]:
    rng = random.Random(seed)
    return [(f"i{i}", rng.random() < p) for i in range(n)]


def obs_with_ids(ids: list[str], p: float, seed: int) -> list[tuple[str, bool]]:
    rng = random.Random(seed)
    return [(i, rng.random() < p) for i in ids]


def test_no_drift_produces_no_detection():
    base = {("slot-a", "money"): obs(180, 0.90, 1)}
    curr = {("slot-a", "money"): obs(180, 0.90, 2)}
    assert not any(a.detected for a in detect_drift(base, curr, look=5, total_looks=13, seed=1))


def test_large_drift_is_detected():
    base = {("slot-a", "money"): obs(180, 0.95, 1)}
    curr = {("slot-a", "money"): obs(180, 0.55, 2)}
    assert any(a.detected for a in detect_drift(base, curr, look=5, total_looks=13, seed=1))


def test_alert_states_its_test():
    base = {("slot-a", "money"): obs(180, 0.95, 1)}
    curr = {("slot-a", "money"): obs(180, 0.55, 2)}
    alert = next(a for a in detect_drift(base, curr, look=5, total_looks=13, seed=1) if a.detected)
    assert "O'Brien-Fleming" in alert.statement
    assert "Benjamini-Hochberg" in alert.statement
    assert "look 5 of 13" in alert.statement


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


def test_no_id_overlap_falls_back_to_current_interval_proxy():
    # Baseline and current share no item ids for this key -- _discordance_rate's paired-by-id
    # path finds an empty intersection and must fall back to the report.py-style proxy:
    # n_items = current interval's n, discordance_rate = max(1 - current.point, 0.01).
    base = {("slot-a", "money"): obs_with_ids([f"b{i}" for i in range(10)], 0.90, 1)}
    curr = {("slot-a", "money"): obs_with_ids([f"c{i}" for i in range(10)], 0.90, 2)}
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1)[0]
    assert not alert.detected
    expected_rate = max(1 - alert.current.point, 0.01)
    assert describe_mde(alert.current.n, expected_rate) in alert.statement


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
        (a.slot, a.field_type): a
        for a in detect_drift(base, curr, look=5, total_looks=13, seed=1)
    }
    assert alerts[("slot-a", "money")].detected
    assert not alerts[("slot-b", "money")].detected
