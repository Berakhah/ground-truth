from __future__ import annotations

from dataclasses import dataclass

import duckdb

from ground_truth.graders.base import Verdict
from ground_truth.graders.deterministic.schema import extract_fields
from ground_truth.graders.judge.aggregate import (
    JudgeVerdict,
    Sample,
    majority_vote,
    parse_judgement,
)

JUDGE_GRADER_VERSION = "1"
_MIN_SAMPLES = 3


class UnassignedSlot(LookupError):
    """A stored output's model slot has no judge assigned: models.yaml no longer lists the slot
    (renamed or retired) or lists it without a `judge`. Raised before any judge call or verdict
    write, so nothing is judged, or scored, by a judge nobody assigned."""

    def __init__(self, slot: str, where: str) -> None:
        super().__init__(
            f"model slot {slot!r} has outputs in the store but no judge assigned for {where}: "
            "models.yaml no longer lists it (renamed or retired?) or names no judge for it. "
            "Restore the slot's entry with its judge, or remove its outputs from this run."
        )
        self.slot = slot


@dataclass(frozen=True)
class JudgeTarget:
    item_id: str
    model_slot: str
    output_id: str
    observed: str | None  # None: the field is modally absent, so there is nothing to judge


def _observed(raw_output: str, field_name: str) -> str | None:
    try:
        value = extract_fields(raw_output).get(field_name)
    except ValueError:
        return None  # unparseable: schema grading already marks it; here it votes as absent
    return None if value is None else str(value)


def select_judge_targets(con: duckdb.DuckDBPyConnection, field_name: str) -> list[JudgeTarget]:
    """One output per (item, slot): the replicate holding the modal value of `field_name`.

    Audit H8 / spec section 15: judging every replicate costs 300 x 6 x 5 x 3 = 27,000 calls;
    judging the modal output costs 5,400 and loses nothing, since replicate variance is
    already measured by the deterministic graders and the calibration signal.

    Outputs are read run-major: runs in start order (run id breaking a tie), then replicates
    within a run, then output id. A value tie goes to the value first seen in that order, and
    the target is the first output in that order holding the modal value. Run-major makes the
    target stable under appended runs: a new run sorts after every existing output, so the
    target moves only when the modal value itself changes. Replicate-major order moved it on
    every re-run (review 2026-10-14, I1), and grading, `run_judging` and `matrix.build` all
    select through this function, so a moved target left the judged field out of the headline
    until the new target was sampled again.
    """
    rows = con.execute(
        "SELECT o.item_id, r.model_slot, o.output_id, o.raw_output FROM outputs o "
        "JOIN runs r ON r.run_id = o.run_id "
        "ORDER BY o.item_id, r.model_slot, r.started_at, o.run_id, o.replicate_idx, o.output_id"
    ).fetchall()
    groups: dict[tuple[str, str], list[tuple[str, str | None]]] = {}
    for item_id, slot, output_id, raw in rows:
        groups.setdefault((item_id, slot), []).append((output_id, _observed(raw, field_name)))
    targets = []
    for (item_id, slot), replicates in groups.items():
        values = [value for _, value in replicates]
        modal = max(dict.fromkeys(values), key=values.count)  # max keeps the first of a tie
        output_id = next(oid for oid, value in replicates if value == modal)
        targets.append(JudgeTarget(item_id, slot, output_id, modal))
    return targets


def judge_verdict(
    con: duckdb.DuckDBPyConnection, target: JudgeTarget, judge_slot: str, field_name: str
) -> Verdict | None:
    """Score a target output from its stored judge samples; `None` while it is unjudged.

    An output with fewer than 3 samples has not been judged, and an unjudged output is not a
    measurement, so nothing is written for it. A modally absent field is scored absent with no
    sample needed (and no judge call was ever made for it).
    """

    def verdict(correct: bool, reason: str) -> Verdict:
        return Verdict(
            correct=correct,
            reason=reason,
            grader_id=f"judge:{judge_slot}",
            grader_version=JUDGE_GRADER_VERSION,
        )

    if target.observed is None:
        return verdict(False, "field not extracted in the modal output; not judged")
    rows = con.execute(
        "SELECT presentation_order, raw_judgement FROM judge_samples "
        "WHERE output_id = ? AND field_name = ? AND judge_slot = ? ORDER BY sample_id",
        [target.output_id, field_name, judge_slot],
    ).fetchall()
    if len(rows) < _MIN_SAMPLES:
        return None
    samples = [Sample(order, raw, len(target.observed)) for order, raw in rows]
    outcome = majority_vote(samples)
    if outcome is JudgeVerdict.INCONCLUSIVE:
        return verdict(False, f"judge inconclusive: no majority in {len(samples)} samples")
    agreeing = sum(1 for s in samples if parse_judgement(s.raw) is outcome)
    return verdict(
        outcome is JudgeVerdict.EQUIVALENT,
        f"judge majority {outcome.value} ({agreeing} of {len(samples)})",
    )
