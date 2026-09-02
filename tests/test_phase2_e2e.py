# tests/test_phase2_e2e.py
from pathlib import Path

import pytest

from ground_truth.analysis_plan import assert_frozen_before_first_sweep
from ground_truth.golden.rubric import loaded_rubric
from ground_truth.golden.schema import FieldType  # noqa: F401
from ground_truth.store.db import connect

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "results.duckdb"


@pytest.fixture()
def con():
    if not DB.exists():
        pytest.skip("run the sweep first: python -m ground_truth.schedule")
    c = connect(DB)
    yield c
    c.close()


def test_pre_registration_held_across_the_real_sweep(con):
    assert_frozen_before_first_sweep(con)


def test_every_slot_has_five_replicates_per_item(con):
    bad = con.execute(
        "SELECT r.model_slot, o.item_id, count(*) c FROM outputs o "
        "JOIN runs r ON r.run_id = o.run_id GROUP BY 1, 2 HAVING c <> 5"
    ).fetchall()
    assert bad == [], f"incomplete replicate sets: {bad[:5]}"


def test_replicates_are_not_all_identical(con):
    """If every replicate matches, the cache was on and the variance is fabricated."""
    identical = con.execute(
        "SELECT count(*) FROM (SELECT o.item_id, r.model_slot FROM outputs o "
        "JOIN runs r ON r.run_id = o.run_id GROUP BY 1, 2 "
        "HAVING count(DISTINCT o.raw_output) = 1)"
    ).fetchone()[0]
    total = con.execute(
        "SELECT count(*) FROM (SELECT o.item_id, r.model_slot FROM outputs o "
        "JOIN runs r ON r.run_id = o.run_id GROUP BY 1, 2)"
    ).fetchone()[0]
    assert identical < total, (
        "every replicate set is identical — check that runner.BENCHMARK_CACHE is False"
    )


def test_provider_served_is_recorded_for_every_call(con):
    missing = con.execute(
        "SELECT count(*) FROM outputs WHERE provider_served IS NULL OR provider_served = ''"
    ).fetchone()[0]
    assert missing == 0, "00 B8: which provider served each call must be recorded"


def test_ledger_call_id_recorded_for_every_call(con):
    missing = con.execute(
        "SELECT count(*) FROM outputs WHERE ledger_call_id IS NULL OR ledger_call_id = ''"
    ).fetchone()[0]
    assert missing == 0, "00 R7: fingerprint tracking depends on the ledger foreign key"


def test_judge_touched_only_the_free_text_field(con):
    fields = {r[0] for r in con.execute("SELECT DISTINCT field_name FROM judge_samples").fetchall()}
    assert fields <= {"line_1_description"}, (
        f"the judge must only score free text; it touched {fields}"
    )


def test_both_presentation_orders_occurred(con):
    orders = {
        r[0]
        for r in con.execute("SELECT DISTINCT presentation_order FROM judge_samples").fetchall()
    }
    assert orders == {0, 1}, "order randomisation did not actually vary the presentation"


def test_every_deterministic_field_type_has_verdicts(con):
    rubric = loaded_rubric(REPO / "docs" / "rubric.md")
    deterministic = {ft.value for ft, rule in rubric.items() if rule.grader != "judge"}
    graded = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT f.field_type FROM verdicts v "
            "JOIN item_fields f ON f.field_name = v.field_name"
        ).fetchall()
    }
    assert deterministic - graded == set(), (
        f"field types with no verdicts: {deterministic - graded}"
    )
