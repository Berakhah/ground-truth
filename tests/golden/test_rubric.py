from pathlib import Path

import pytest

from ground_truth.golden.rubric import freeze_rubric, loaded_rubric
from ground_truth.golden.schema import FieldType
from ground_truth.store.db import connect, migrate

REPO = Path(__file__).resolve().parents[2]
RUBRIC = REPO / "docs" / "rubric.md"


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def test_rubric_covers_every_field_type():
    rules = loaded_rubric(RUBRIC)
    assert set(rules) == set(FieldType), "every field type needs a written rule before labelling"


def test_money_rule_declares_a_decimal_tolerance():
    rule = loaded_rubric(RUBRIC)[FieldType.MONEY]
    assert rule.tolerance is not None and rule.grader == "numeric_tolerance"


def test_freeze_records_hash_and_timestamp(con):
    digest = freeze_rubric(con, RUBRIC, "v1")
    row = con.execute(
        "SELECT content_hash, frozen_at FROM rubric_versions WHERE rubric_version='v1'"
    ).fetchone()
    assert row[0] == digest and row[1] is not None


def test_freeze_is_idempotent_for_unchanged_content(con):
    assert freeze_rubric(con, RUBRIC, "v1") == freeze_rubric(con, RUBRIC, "v1")


def test_freeze_is_refused_when_content_changed(con, tmp_path):
    freeze_rubric(con, RUBRIC, "v1")
    altered = tmp_path / "rubric.md"
    altered.write_text(RUBRIC.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    with pytest.raises(ValueError, match="already frozen"):
        freeze_rubric(con, altered, "v1")
