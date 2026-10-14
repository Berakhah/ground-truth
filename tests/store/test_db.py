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


# -- judge_decisions keyed per (field type, judge) ------------------------------------------

# The shape every store had before decisions were keyed per judge: one row per field type.
_OLD_JUDGE_DECISIONS = """
CREATE TABLE judge_decisions (
    field_type TEXT PRIMARY KEY, rubric_version TEXT NOT NULL, alpha DOUBLE NOT NULL,
    alpha_low DOUBLE NOT NULL, alpha_high DOUBLE NOT NULL, n_units INTEGER NOT NULL,
    threshold DOUBLE NOT NULL, status TEXT NOT NULL CHECK (status IN ('accepted','rejected')),
    decided_at TIMESTAMPTZ NOT NULL, statement TEXT, alpha_method TEXT);
"""


def _judge_decision_columns(c: duckdb.DuckDBPyConnection) -> set[str]:
    return {
        r[0]
        for r in c.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'judge_decisions'"
        ).fetchall()
    }


def test_judge_decisions_are_keyed_per_field_type_and_judge(con):
    insert = (
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at) "
        "VALUES ('money', ?, 'v1', 0.9, 0.8, 0.95, 60, 0.667, 'accepted', now())"
    )
    con.execute(insert, ["judge-a"])
    con.execute(insert, ["judge-b"])
    with pytest.raises(duckdb.ConstraintException):
        con.execute(insert, ["judge-a"])


def test_judge_slot_is_required(con):
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO judge_decisions (field_type, rubric_version, alpha, alpha_low, "
            "alpha_high, n_units, threshold, status, decided_at) "
            "VALUES ('money', 'v1', 0.9, 0.8, 0.95, 60, 0.667, 'accepted', now())"
        )


def test_migrate_refuses_to_re_key_old_judge_decisions_that_hold_rows(tmp_path):
    """A decision recorded before decisions were keyed per judge does not say which judge it
    assessed; assigning it to one would publish an agreement figure for a judge it was never
    measured against, so `migrate` stops and leaves the store as it found it."""
    c = connect(tmp_path / "old.duckdb")
    c.execute(_OLD_JUDGE_DECISIONS)
    c.execute(
        "INSERT INTO judge_decisions VALUES ('money', 'v1', 0.9, 0.8, 0.95, 60, 0.667, "
        "'accepted', now(), NULL, NULL)"
    )
    with pytest.raises(RuntimeError, match="judge_decisions") as raised:
        migrate(c)
    assert "cannot be re-keyed honestly" in str(raised.value)
    assert c.execute("SELECT count(*) FROM judge_decisions").fetchone()[0] == 1
    assert "judge_slot" not in _judge_decision_columns(c)
    c.close()


def test_migrate_rebuilds_an_empty_old_judge_decisions_table(tmp_path):
    c = connect(tmp_path / "old-empty.duckdb")
    c.execute(_OLD_JUDGE_DECISIONS)
    migrate(c)
    assert "judge_slot" in _judge_decision_columns(c)
    pk = c.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name = 'judge_decisions' AND constraint_type = 'PRIMARY KEY'"
    ).fetchone()
    assert pk is not None and sorted(pk[0]) == ["field_type", "judge_slot"]
    migrate(c)  # the rebuilt table is left alone on the next run
    c.close()
