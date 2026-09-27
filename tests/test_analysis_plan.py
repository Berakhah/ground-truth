from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ground_truth.analysis_plan import assert_frozen_before_first_sweep, freeze_plan
from ground_truth.store.db import connect, migrate

PLAN = Path(__file__).resolve().parents[1] / "docs" / "analysis-plan.md"


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def _insert_run(con, started_at):
    con.execute(
        "INSERT INTO runs VALUES (?,?,NULL,'slot-a','ref','prov',false,'s1','sha','h')",
        [f"r{started_at.timestamp()}", started_at],
    )


def test_plan_states_the_judge_threshold():
    assert "0.667" in PLAN.read_text(encoding="utf-8"), (
        "the rejection threshold must be pre-registered"
    )


def test_plan_states_the_per_look_boundary():
    """The plan commits to the regression watch's boundary before any sweep, not just the code."""
    assert "2.8831" in PLAN.read_text(encoding="utf-8"), (
        "the per-look Šidák boundary must be pre-registered"
    )


def test_plan_v2_records_what_it_replaced_and_that_v1_governed_no_look():
    """A post-freeze procedure change needs a new plan_version, never a silent edit of v1 --
    and the record must show the change came before any data it could have been fitted to."""
    text = " ".join(PLAN.read_text(encoding="utf-8").split())  # prose wraps across lines
    assert "plan_version: v2" in text
    assert "v1 governed zero looks" in text
    assert "Superseded: v1" in text and "C = 2.1023" in text, "v1's text is kept for the record"


def test_plan_names_the_sampling_unit():
    assert "item" in PLAN.read_text(encoding="utf-8").lower()


def test_no_runs_yet_is_not_a_violation(con):
    freeze_plan(con, PLAN, "v1")
    assert_frozen_before_first_sweep(con)


def test_passes_when_plan_frozen_first(con):
    freeze_plan(con, PLAN, "v1")
    _insert_run(con, datetime.now(UTC) + timedelta(hours=1))
    assert_frozen_before_first_sweep(con)


def test_fails_when_a_sweep_predates_the_plan(con):
    _insert_run(con, datetime.now(UTC) - timedelta(days=1))
    freeze_plan(con, PLAN, "v1")
    with pytest.raises(AssertionError, match="pre-registration"):
        assert_frozen_before_first_sweep(con)
