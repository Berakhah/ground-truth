from pathlib import Path

import pytest

from ground_truth.graders.judge.aggregate import Sample
from ground_truth.graders.judge.agreement import REJECTION_THRESHOLD, JudgeStatus, assess

PLAN = Path(__file__).resolve().parents[3] / "docs" / "analysis-plan.md"


def samples(n: int = 20) -> list[Sample]:
    return [
        Sample(presentation_order=i % 2, raw="EQUIVALENT", observed_length=10 + i) for i in range(n)
    ]


def agreeing(n: int):
    j = {str(i): ("EQUIVALENT" if i % 3 else "NOT_EQUIVALENT") for i in range(n)}
    return j, dict(j)


def disagreeing(n: int):
    j = {str(i): "EQUIVALENT" for i in range(n)}
    h = {str(i): ("EQUIVALENT" if i % 2 else "NOT_EQUIVALENT") for i in range(n)}
    return j, h


def test_threshold_matches_the_pre_registered_plan():
    assert str(REJECTION_THRESHOLD) in PLAN.read_text(encoding="utf-8"), (
        "the threshold in code must be the one frozen in docs/analysis-plan.md"
    )


def test_high_agreement_is_accepted():
    j, h = agreeing(60)
    report = assess("line_item_description", j, h, samples(), seed=1)
    assert report.status is JudgeStatus.ACCEPTED and report.alpha > REJECTION_THRESHOLD


def test_low_agreement_is_rejected():
    j, h = disagreeing(60)
    assert assess("line_item_description", j, h, samples(), seed=1).status is JudgeStatus.REJECTED


def test_rejected_report_states_the_consequence():
    j, h = disagreeing(60)
    statement = assess("line_item_description", j, h, samples(), seed=1).statement
    assert "not used for headline scoring" in statement
    assert str(REJECTION_THRESHOLD) in statement


def test_accepted_report_still_publishes_its_alpha_and_interval():
    j, h = agreeing(60)
    report = assess("line_item_description", j, h, samples(), seed=1)
    assert f"n={report.n_units}" in report.statement
    assert report.alpha_ci.low <= report.alpha_ci.high


def test_confusion_matrix_is_included():
    j, h = agreeing(60)
    assert assess("line_item_description", j, h, samples(), seed=1).confusion


def test_bias_measures_are_included():
    j, h = agreeing(60)
    report = assess("line_item_description", j, h, samples(), seed=1)
    assert report.order.n > 0 and len(report.length.quintile_rates) == 5  # noqa: PLR2004


def test_no_overlapping_units_raises_rather_than_reporting_perfect_agreement():
    with pytest.raises(ValueError, match="no overlapping"):
        assess("line_item_description", {"1": "EQUIVALENT"}, {"2": "EQUIVALENT"}, samples(), seed=1)
