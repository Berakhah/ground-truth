import json
import uuid
from pathlib import Path

import pytest

from ground_truth.golden.rubric import loaded_rubric
from ground_truth.golden.schema import FieldType, Item, ItemField, Source, Split
from ground_truth.grade import grade_stored_outputs
from ground_truth.store.db import connect, migrate

RUBRIC = Path(__file__).resolve().parents[3] / "docs" / "rubric.md"
FIELD = "line_1_description"
JUDGES = {"slot-a": "judge-a"}


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def _output(con, *, item_id, slot, replicate, raw):
    run_id = f"run-{slot}"
    con.execute(
        "INSERT OR IGNORE INTO runs (run_id, started_at, model_slot, resolved_model_ref, "
        "provider, commercial_context, sweep_id, code_version, models_yaml_hash) "
        "VALUES (?, now(), ?, 'ref', 'prov', false, 's1', 'sha', 'h')",
        [run_id, slot],
    )
    output_id = f"o-{item_id}-{slot}-{replicate}"
    con.execute(
        "INSERT INTO outputs (output_id, run_id, item_id, replicate_idx, raw_output, "
        "ledger_call_id, provider_served, latency_ms, prompt_hash, observed_at) "
        "VALUES (?, ?, ?, ?, ?, 'call', 'prov', 10, 'ph', now())",
        [output_id, run_id, item_id, replicate, raw],
    )
    return output_id


def _desc(value):
    return json.dumps({FIELD: value})


def _items():
    return [
        Item(
            item_id="i1",
            split=Split.PUBLIC,
            rubric_version="v1",
            source=Source.SYNTHETIC,
            content_hash="h",
            fields=[
                ItemField(
                    field_name=FIELD,
                    field_type=FieldType.LINE_ITEM_DESCRIPTION,
                    expected_value="Concrete works, phase 1",
                )
            ],
        )
    ]


def _store(con, raws=None):
    raws = raws or [_desc("Concrete works")] * 5
    ids = [
        _output(con, item_id="i1", slot="slot-a", replicate=r, raw=raw)
        for r, raw in enumerate(raws, start=1)
    ]
    return ids


def _samples(con, output_id, raws):
    for i, raw in enumerate(raws):
        con.execute(
            "INSERT INTO judge_samples VALUES (?,?,?,?,?,?,?,?)",
            [uuid.uuid4().hex, output_id, FIELD, "judge-a", i % 2, raw, "call", "2026-01-01"],
        )


def _judge_verdicts(con):
    return con.execute(
        "SELECT output_id, field_name, grader_id, grader_version, correct, reason "
        "FROM verdicts WHERE grader_id LIKE 'judge:%' ORDER BY output_id"
    ).fetchall()


def _grade(con, judges=JUDGES):
    return grade_stored_outputs(con, _items(), loaded_rubric(RUBRIC), judges=judges)


def test_majority_equivalent_is_correct_on_the_target_output_only(con):
    ids = _store(con)
    _samples(con, ids[0], ["EQUIVALENT", "EQUIVALENT", "NOT_EQUIVALENT"])
    _grade(con)
    assert _judge_verdicts(con) == [
        (ids[0], FIELD, "judge:judge-a", "1", True, "judge majority EQUIVALENT (2 of 3)")
    ]


def test_majority_not_equivalent_is_incorrect(con):
    ids = _store(con)
    _samples(con, ids[0], ["NOT_EQUIVALENT", "NOT_EQUIVALENT", "NOT_EQUIVALENT"])
    _grade(con)
    ((_, _, _, _, correct, reason),) = _judge_verdicts(con)
    assert correct is False
    assert reason == "judge majority NOT_EQUIVALENT (3 of 3)"


def test_a_tie_is_inconclusive_and_scores_incorrect(con):
    ids = _store(con)
    _samples(con, ids[0], ["EQUIVALENT", "NOT_EQUIVALENT", "garbage"])
    _grade(con)
    ((_, _, _, _, correct, reason),) = _judge_verdicts(con)
    assert correct is False
    assert reason.startswith("judge inconclusive: ")
    assert reason == "judge inconclusive: no majority in 3 samples"


def test_a_modally_absent_field_scores_absent_without_a_judge_call(con):
    ids = _store(con, ["not json"] * 5)
    _grade(con)
    assert _judge_verdicts(con) == [
        (
            ids[0],
            FIELD,
            "judge:judge-a",
            "1",
            False,
            "field not extracted in the modal output; not judged",
        )
    ]


def test_fewer_than_three_samples_writes_no_verdict(con):
    ids = _store(con)
    _samples(con, ids[0], ["EQUIVALENT", "EQUIVALENT"])
    _grade(con)
    assert _judge_verdicts(con) == []


def test_regrading_writes_nothing_new(con):
    ids = _store(con)
    _samples(con, ids[0], ["EQUIVALENT", "EQUIVALENT", "NOT_EQUIVALENT"])
    _grade(con)
    assert _grade(con) == 0
    assert len(_judge_verdicts(con)) == 1


def test_without_judges_no_judge_verdict_is_written(con):
    ids = _store(con)
    _samples(con, ids[0], ["EQUIVALENT", "EQUIVALENT", "NOT_EQUIVALENT"])
    _grade(con, judges=None)
    assert _judge_verdicts(con) == []
