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


def test_plan_states_the_calibrated_obf_constant():
    """audit B3: the naive z_{alpha/2}=1.96 boundary understates true alpha as 0.0721
    against the nominal 0.05. The pre-registered plan must commit to the calibrated
    constant before any sweep, not just the code in Phase 2."""
    assert "2.1023" in PLAN.read_text(encoding="utf-8"), (
        "the calibrated OBF constant must be pre-registered"
    )


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
