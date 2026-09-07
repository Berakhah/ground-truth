# tests/regression/test_detect.py
import random

import pytest

from ground_truth.regression.detect import detect_drift


def obs(n: int, p: float, seed: int) -> list[tuple[str, bool]]:
    rng = random.Random(seed)
    return [(f"i{i}", rng.random() < p) for i in range(n)]


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
