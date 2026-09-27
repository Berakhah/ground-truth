import json
import math
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


def unanimous(n: int):
    j = {str(i): "EQUIVALENT" for i in range(n)}
    return j, dict(j)


def test_single_category_unanimity_is_rejected_not_a_crash():
    """Every unit gets the same verdict from both raters, so expected disagreement is zero and
    alpha is 0/0. A judge that always says EQUIVALENT is indistinguishable from a perfect one on
    this sample, so it cannot clear the threshold -- and a crash here would leave no
    judge_decisions row, which `matrix.build` reads as "no decision" and scores the judge."""
    j, h = unanimous(60)
    report = assess("line_item_description", j, h, samples(), seed=1, n_resamples=200)
    assert report.status is JudgeStatus.REJECTED
    assert math.isnan(report.alpha)
    assert math.isnan(report.alpha_ci.low) and math.isnan(report.alpha_ci.high)
    assert report.n_units == 60  # noqa: PLR2004


def test_single_category_unanimity_statement_says_alpha_is_undefined():
    j, h = unanimous(60)
    statement = assess("line_item_description", j, h, samples(), seed=1).statement
    assert "undefined" in statement
    assert "n=60" in statement
    assert "EQUIVALENT" in statement
    assert "not used for headline scoring" in statement
    assert "nan" not in statement.lower()


def test_undefined_alpha_is_recorded_as_rejected(tmp_path):
    from ground_truth.graders.judge.agreement import record_decision  # noqa: PLC0415
    from ground_truth.store.db import connect, migrate  # noqa: PLC0415

    j, h = unanimous(60)
    report = assess("line_item_description", j, h, samples(), seed=1, n_resamples=200)
    con = connect(tmp_path / "undefined-alpha.duckdb")
    migrate(con)
    record_decision(con, report, rubric_version="v1")
    status = con.execute("SELECT status FROM judge_decisions").fetchone()
    con.close()
    assert status == ("rejected",)


def test_undefined_alpha_publishes_as_valid_json(tmp_path):
    """`json.dumps` writes a NaN float as the bare token NaN, which is not JSON."""
    from datetime import UTC, datetime  # noqa: PLC0415

    from ground_truth.publish.leaderboard import (  # noqa: PLC0415
        leaderboard_payload,
        write_leaderboard,
    )

    j, h = unanimous(60)
    report = assess("line_item_description", j, h, samples(), seed=1, n_resamples=200)
    path = tmp_path / "leaderboard.json"
    as_of = datetime(2026, 9, 27, tzinfo=UTC)
    write_leaderboard(leaderboard_payload([], [], [report], [], as_of=as_of, version="t"), path)
    published = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    entry = published["judge_agreement"][0]
    assert entry["alpha"] is None
    assert entry["alpha_ci"]["low"] is None and entry["alpha_ci"]["high"] is None


def _reject_constant(token: str) -> None:
    raise AssertionError(f"published JSON contains the non-JSON token {token}")


def test_no_overlapping_units_raises_rather_than_reporting_perfect_agreement():
    with pytest.raises(ValueError, match="no overlapping"):
        assess("line_item_description", {"1": "EQUIVALENT"}, {"2": "EQUIVALENT"}, samples(), seed=1)


def minority_disagreement():
    """9 agreeing EQUIVALENT units + 1 disagreement: alpha is defined on the full sample, but
    any resample that misses the disagreement unit is 0/0 and is excluded."""
    j = {str(i): "EQUIVALENT" for i in range(10)}
    h = dict(j) | {"9": "NOT_EQUIVALENT"}
    return j, h


def test_an_interval_with_no_defined_resample_is_rejected():
    """No defined resample means no interval, so the judge cannot be defended (rule 3)."""
    j, h = minority_disagreement()
    report = assess("line_item_description", j, h, samples(), seed=3, n_resamples=2)
    assert report.status is JudgeStatus.REJECTED
    assert "interval could not be estimated" in report.statement
    assert "nan" not in report.statement.lower()


def test_statement_discloses_excluded_resamples():
    """The interval is conditional on alpha being defined, which trims the most-agreeing
    resamples; a published sentence that hides that overstates what the interval says
    (stats code review 2026-09-27 #2, findings 3 and 4)."""
    j, h = minority_disagreement()
    report = assess("line_item_description", j, h, samples(), seed=1, n_resamples=400)
    assert "undefined resamples excluded" in report.alpha_ci.method
    assert "undefined resamples excluded" in report.statement
    assert "conditional on alpha being defined" in report.statement


def test_record_decision_stores_the_statement_and_interval_method(tmp_path):
    """The publisher must publish what `assess` said, not rebuild a reason from a NaN
    (stats code review 2026-09-27 #2, findings 4 and 6)."""
    from ground_truth.graders.judge.agreement import record_decision  # noqa: PLC0415
    from ground_truth.store.db import connect, migrate  # noqa: PLC0415

    j, h = minority_disagreement()
    report = assess("line_item_description", j, h, samples(), seed=1, n_resamples=400)
    con = connect(tmp_path / "stored.duckdb")
    migrate(con)
    record_decision(con, report, rubric_version="v1")
    stored = con.execute("SELECT statement, alpha_method FROM judge_decisions").fetchone()
    con.close()
    assert stored == (report.statement, report.alpha_ci.method)
