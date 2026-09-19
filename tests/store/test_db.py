from pathlib import Path

import duckdb
import pytest

from ground_truth.store.db import TABLES, connect, migrate

EXPECTED = (
    "rubric_versions",
    "analysis_plan",
    "items",
    "item_fields",
    "runs",
    "outputs",
    "judge_samples",
    "verdicts",
    "human_labels",
    "judge_decisions",
    "looks",
    "rotations",
)


@pytest.fixture()
def con(tmp_path: Path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def test_all_tables_exist(con):
    present = {
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    assert set(EXPECTED) <= present


def test_tables_constant_matches_schema(con):
    assert set(TABLES) == set(EXPECTED)


def test_migrate_is_idempotent(con):
    migrate(con)
    migrate(con)
    assert con.execute("SELECT count(*) FROM outputs").fetchone()[0] == 0


def test_outputs_rejects_duplicate_replicate(con):
    con.execute(
        "INSERT INTO runs VALUES ('r1', now(), NULL, 'slot-a', 'ref', 'prov', false, 's1',"
        " 'sha', 'h')"
    )
    row = ("o1", "r1", "i1", 1, "{}", "call1", "prov", None, 100, "ph", "2026-09-01", None)
    con.execute("INSERT INTO outputs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO outputs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("o2", "r1", "i1", 1, "{}", "call2", "prov", None, 100, "ph", "2026-09-01", None),
        )


def test_split_check_constraint_rejects_a_third_split(con):
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO items (item_id, split, rubric_version, source, content_hash, "
            "created_at) VALUES ('i1', 'holdout', 'v1', 'synthetic', 'h', now())"
        )
