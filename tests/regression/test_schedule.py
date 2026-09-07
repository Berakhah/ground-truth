# tests/regression/test_schedule.py
from datetime import UTC, datetime, timedelta

import pytest

from ground_truth.regression.schedule import (
    LookRecord,
    next_look,
    record_look,
    unscheduled_look_warning,
)
from ground_truth.stats.sequential import LOOKS_PER_QUARTER
from ground_truth.store.db import connect, migrate


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def test_first_look_of_a_quarter_is_one(con):
    record = next_look(con, datetime(2026, 10, 5, tzinfo=UTC))
    assert record.look == 1 and record.total_looks == LOOKS_PER_QUARTER


def test_looks_increment_within_a_quarter(con):
    now = datetime(2026, 10, 5, tzinfo=UTC)
    record_look(con, next_look(con, now))
    assert next_look(con, now + timedelta(days=7)).look == 2  # noqa: PLR2004


def test_a_new_quarter_resets_the_look_counter(con):
    record_look(con, next_look(con, datetime(2026, 10, 5, tzinfo=UTC)))
    assert next_look(con, datetime(2027, 1, 5, tzinfo=UTC)).look == 1


def test_quarter_label_is_recorded(con):
    assert next_look(con, datetime(2026, 10, 5, tzinfo=UTC)).quarter == "2026Q4"


def test_exceeding_the_calendar_warns_about_spent_alpha():
    record = LookRecord(
        quarter="2026Q4",
        look=LOOKS_PER_QUARTER + 1,
        total_looks=LOOKS_PER_QUARTER,
        run_at=datetime(2026, 12, 30, tzinfo=UTC),
    )
    warning = unscheduled_look_warning(record)
    assert warning is not None and "alpha" in warning and "changelog" in warning


def test_a_scheduled_look_produces_no_warning(con):
    assert unscheduled_look_warning(next_look(con, datetime(2026, 10, 5, tzinfo=UTC))) is None


def test_recording_the_same_look_twice_raises(con):
    now = datetime(2026, 10, 5, tzinfo=UTC)
    record = next_look(con, now)
    record_look(con, record)
    with pytest.raises(Exception):  # noqa: B017
        record_look(con, record)
