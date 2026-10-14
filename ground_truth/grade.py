"""Phase-2 grading pass: reads the immutable `outputs` table, writes `verdicts`.

Deterministic only -- imports nothing from the runner module or the provider-gateway
shim, which is what makes degraded mode (`tests/test_degraded_mode.py`) an architectural
fact rather than a runtime measurement: grading needs zero gateway calls, full stop.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import duckdb

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import FieldType, Item
from ground_truth.graders.base import Verdict
from ground_truth.graders.deterministic.arithmetic import grade_arithmetic
from ground_truth.graders.deterministic.exact import grade_exact
from ground_truth.graders.deterministic.normalised import grade_normalised
from ground_truth.graders.deterministic.numeric_tolerance import grade_numeric_tolerance
from ground_truth.graders.deterministic.schema import extract_fields, grade_schema
from ground_truth.graders.judge.targets import JudgeTarget, judge_verdict, select_judge_targets

_SCHEMA_FIELD = "__schema__"
_ARITHMETIC_FIELD = "__arithmetic__"


def _verdict_count(con: duckdb.DuckDBPyConnection) -> int:
    row = con.execute("SELECT count(*) FROM verdicts").fetchone()
    # SELECT count(*) always returns exactly one row; the assertion documents that
    # invariant for mypy's benefit, it never fires.
    assert row is not None
    return int(row[0])


def _write_verdict(
    con: duckdb.DuckDBPyConnection,
    output_id: str,
    field_name: str,
    rubric_version: str,
    verdict: Verdict,
) -> None:
    con.execute(
        "INSERT OR IGNORE INTO verdicts VALUES (?,?,?,?,?,?,?,?,?)",
        [
            uuid.uuid4().hex,
            output_id,
            field_name,
            verdict.grader_id,
            verdict.grader_version,
            rubric_version,
            verdict.correct,
            verdict.reason,
            datetime.now(UTC),
        ],
    )


def grade_stored_outputs(  # noqa: PLR0912 -- explicit dispatch chain, not a lookup table
    con: duckdb.DuckDBPyConnection,
    items: list[Item],
    rubric: dict[FieldType, RubricRule],
    *,
    judges: dict[str, str] | None = None,
) -> int:
    """Grade every row currently in `outputs` and write verdicts, idempotently.

    `INSERT OR IGNORE` against verdicts' `UNIQUE (output_id, field_name, grader_id,
    grader_version, rubric_version)` constraint means re-grading at the same rubric
    version writes nothing new, so the return value counts rows genuinely new to
    `verdicts` (a before/after count), not attempted writes -- "written" means written.
    """
    money_tolerance = rubric[FieldType.MONEY].tolerance
    if money_tolerance is None:
        raise ValueError("rubric declares no MONEY tolerance; arithmetic checks require one")

    by_item_id = {item.item_id: item for item in items}
    before = _verdict_count(con)

    # Judge verdicts exist only when the caller supplies the model-slot -> judge-slot map; with
    # None, judge fields are skipped exactly as before (degraded mode, existing callers).
    judge_targets: dict[tuple[str, str], JudgeTarget] = {}
    if judges is not None:
        judge_field_names = {
            f.field_name
            for item in items
            for f in item.fields
            if rubric[f.field_type].grader == "judge"
        }
        judge_targets = {
            (t.output_id, name): t
            for name in judge_field_names
            for t in select_judge_targets(con, name)
        }

    def write_judge(output_id: str, model_slot: str, item: Item, field_name: str) -> None:
        target = judge_targets.get((output_id, field_name))
        if target is None or judges is None:
            return  # not the modal output of its (item, slot), or judging is off
        verdict = judge_verdict(con, target, judges[model_slot], field_name)
        if verdict is not None:
            _write_verdict(con, output_id, field_name, item.rubric_version, verdict)

    rows = con.execute(
        "SELECT o.output_id, o.item_id, o.raw_output, r.model_slot FROM outputs o "
        "JOIN runs r ON r.run_id = o.run_id"
    ).fetchall()
    for output_id, item_id, raw_output, model_slot in rows:
        item = by_item_id[item_id]

        schema_verdict = grade_schema(item, raw_output)
        _write_verdict(con, output_id, _SCHEMA_FIELD, item.rubric_version, schema_verdict)
        if not schema_verdict.correct:
            # An unparseable target is still the modal target and must score as absent.
            for field in item.fields:
                if rubric[field.field_type].grader == "judge":
                    write_judge(output_id, model_slot, item, field.field_name)
            continue

        observed = extract_fields(raw_output)
        for field in item.fields:
            rule = rubric[field.field_type]
            grader_name = rule.grader
            if grader_name == "exact":
                verdict = grade_exact(field, observed.get(field.field_name), rule)
            elif grader_name == "numeric_tolerance":
                verdict = grade_numeric_tolerance(field, observed.get(field.field_name), rule)
            elif grader_name == "normalised":
                verdict = grade_normalised(field, observed.get(field.field_name), rule)
            elif grader_name == "judge":
                write_judge(output_id, model_slot, item, field.field_name)
                continue
            else:
                raise ValueError(f"rubric declares unknown grader {grader_name!r}")
            _write_verdict(con, output_id, field.field_name, item.rubric_version, verdict)

        arithmetic_verdict = grade_arithmetic(item, observed, money_tolerance)
        _write_verdict(con, output_id, _ARITHMETIC_FIELD, item.rubric_version, arithmetic_verdict)

    return _verdict_count(con) - before
