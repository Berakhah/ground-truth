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
from ground_truth.graders.judge.targets import (
    JudgeTarget,
    UnassignedSlot,
    judge_verdict,
    select_judge_targets,
)

_SCHEMA_FIELD = "__schema__"
_ARITHMETIC_FIELD = "__arithmetic__"
_JUDGE_GRADER_PREFIX = "judge:"


class GradingConflict(RuntimeError):
    """A re-grade reached a different answer than a stored verdict with the same key.

    Verdicts are append-only and keyed by (output, field, grader, grader version, rubric
    version), so the key carries no outcome. A deterministic grader that disagrees with itself at
    the same version means an output or the grader changed without a version bump; the stored
    verdict stays, and the version has to be bumped for the new answer to be recorded.
    """


def _verdict_count(con: duckdb.DuckDBPyConnection) -> int:
    row = con.execute("SELECT count(*) FROM verdicts").fetchone()
    # SELECT count(*) always returns exactly one row; the assertion documents that
    # invariant for mypy's benefit, it never fires.
    assert row is not None
    return int(row[0])


def _write_verdict(  # noqa: PLR0913, PLR0917 -- one verdict row's key plus the conflict sink
    con: duckdb.DuckDBPyConnection,
    output_id: str,
    field_name: str,
    rubric_version: str,
    verdict: Verdict,
    conflicts: list[str],
) -> None:
    # The key (output, field, grader, grader version, rubric version) carries no outcome, so look
    # it up first. A key that exists is left alone: for a judge verdict, a majority over stored
    # samples, another sample at the same grader version can legitimately change it, so that is not
    # a conflict; only a deterministic grader disagreeing with itself is. A new key is a plain
    # INSERT. `INSERT OR IGNORE` here checked every row against the unique index and cost 6-10 ms
    # a row against ~1 ms for a plain INSERT, 99% of a grading pass (profiled 2026-10-18).
    stored = con.execute(
        "SELECT correct FROM verdicts WHERE output_id = ? AND field_name = ? "
        "AND grader_id = ? AND grader_version = ? AND rubric_version = ?",
        [output_id, field_name, verdict.grader_id, verdict.grader_version, rubric_version],
    ).fetchone()
    if stored is not None:
        if not verdict.grader_id.startswith(_JUDGE_GRADER_PREFIX) and (
            bool(stored[0]) != verdict.correct
        ):
            conflicts.append(
                f"{output_id} {field_name} ({verdict.grader_id} v{verdict.grader_version}, "
                f"rubric {rubric_version}): stored correct={bool(stored[0])}, "
                f"re-grade correct={verdict.correct}"
            )
        return  # the stored verdict is left alone either way
    con.execute(
        "INSERT INTO verdicts VALUES (?,?,?,?,?,?,?,?,?)",
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

    The ignore is silent only when the re-grade agrees. A deterministic verdict that disagrees
    with the stored one at the same grader version (an output or a grader changed under the
    record, JP-2) is not written, and the pass raises `GradingConflict` once it has finished.
    """
    money_tolerance = rubric[FieldType.MONEY].tolerance
    if money_tolerance is None:
        raise ValueError("rubric declares no MONEY tolerance; arithmetic checks require one")

    by_item_id = {item.item_id: item for item in items}
    before = _verdict_count(con)
    conflicts: list[str] = []

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
        # Checked before any verdict is written: a slot with no judge stops the pass whole.
        unassigned = sorted({t.model_slot for t in judge_targets.values()} - judges.keys())
        if unassigned:
            raise UnassignedSlot(unassigned[0], "grading")

    def write_judge(output_id: str, model_slot: str, item: Item, field_name: str) -> None:
        target = judge_targets.get((output_id, field_name))
        if target is None or judges is None:
            return  # not the modal output of its (item, slot), or judging is off
        verdict = judge_verdict(con, target, judges[model_slot], field_name)
        if verdict is not None:
            _write_verdict(con, output_id, field_name, item.rubric_version, verdict, conflicts)

    rows = con.execute(
        "SELECT o.output_id, o.item_id, o.raw_output, r.model_slot FROM outputs o "
        "JOIN runs r ON r.run_id = o.run_id"
    ).fetchall()
    for output_id, item_id, raw_output, model_slot in rows:
        item = by_item_id[item_id]

        schema_verdict = grade_schema(item, raw_output)
        _write_verdict(
            con, output_id, _SCHEMA_FIELD, item.rubric_version, schema_verdict, conflicts
        )
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
            _write_verdict(
                con, output_id, field.field_name, item.rubric_version, verdict, conflicts
            )

        arithmetic_verdict = grade_arithmetic(item, observed, money_tolerance)
        _write_verdict(
            con, output_id, _ARITHMETIC_FIELD, item.rubric_version, arithmetic_verdict, conflicts
        )

    if conflicts:
        raise GradingConflict(
            f"{len(conflicts)} re-graded verdict(s) disagree with the stored verdict at the same "
            "grader version; the stored verdicts were kept. Bump the grader version to record the "
            "new answer:\n" + "\n".join(conflicts)
        )
    return _verdict_count(con) - before
