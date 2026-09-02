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


def test_alpha_interval_is_alphas_own_interval_not_the_raw_agreement_rates():
    """Regression: `alpha_ci` used to be `cluster_bootstrap_ci` over per-unit raw agreement.

    Alpha is chance-corrected and raw agreement is not, so under class imbalance the two
    diverge hard. On this fixture the judge says EQUIVALENT for all 60 units and the human
    agrees on half, which puts alpha at -0.322 while the raw agreement rate sits at 0.500 --
    the published "alpha = -0.322 [0.373, 0.627]" sentence carried an interval that did not
    contain its own point estimate. CLAUDE.md rules 2 and 3 both require the interval to
    describe the uncertainty of the number it is attached to.
    """
    j, h = disagreeing(60)
    report = assess("line_item_description", j, h, samples(), seed=1, n_resamples=400)

    raw_rate = sum(j[u] == h[u] for u in j) / len(j)
    assert report.alpha < 0 < raw_rate, "fixture must be one where alpha and raw rate diverge"

    assert report.alpha_ci.low <= report.alpha <= report.alpha_ci.high
    assert report.alpha_ci.point == report.alpha
    assert not (report.alpha_ci.low <= raw_rate <= report.alpha_ci.high), (
        "the interval still brackets the raw agreement rate, so it is not alpha's interval"
    )
    assert f"{report.alpha_ci.low:.3f}" in report.statement


def test_perfect_agreement_does_not_publish_a_zero_width_interval():
    """audit H5, arriving in the judge statement: with zero disagreements every bootstrap
    resample returns alpha = 1.0, so a bare percentile bootstrap would publish
    "1.000 [1.000, 1.000], n=60" -- no uncertainty at all, at exactly the point the claim is
    strongest. `stats.bootstrap` already refuses that for accuracy; so must this."""
    j, h = agreeing(60)
    report = assess("line_item_description", j, h, samples(), seed=1, n_resamples=400)
    assert report.alpha == 1.0
    assert report.alpha_ci.low < report.alpha_ci.high
    assert report.alpha_ci.low > REJECTION_THRESHOLD, "the bound is exact, not merely wide"


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
