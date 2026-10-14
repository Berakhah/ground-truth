from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from ground_truth._bok_shim import (
    CacheMode,
    CallContext,
    FailoverMode,
    Handle,
    Labelled,
    Response,
    Sensitivity,
)
from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import FieldType, Item, ItemField
from ground_truth.graders.judge.targets import JudgeTarget, select_judge_targets
from ground_truth.policy import assert_slot_may_see
from ground_truth.providers import SameFamilyJudge, judge_assignments, load_slots

__all__ = ["JudgeTarget", "run_judging", "select_judge_targets"]


@dataclass(frozen=True)
class Presentation:
    order: int
    first: str
    second: str


def randomise_presentation(expected: str, observed: str, *, seed: int) -> Presentation:
    order = random.Random(seed).randint(0, 1)
    return (
        Presentation(0, expected, observed) if order == 0 else Presentation(1, observed, expected)
    )


def build_judgement_prompt(field: ItemField, presentation: Presentation) -> str:
    return (
        "Two descriptions of the same line item on a progress billing document are given "
        "below. Decide whether they convey the same work.\n\n"
        f"Text A:\n{presentation.first}\n\nText B:\n{presentation.second}\n\n"
        "Reply with exactly one token and nothing else: EQUIVALENT or NOT_EQUIVALENT."
    )


def assert_judge_family_differs(judge_slot: str, model_slot: str, models_yaml: Path) -> None:
    judges = load_slots(models_yaml, key="judge_slots")
    models = load_slots(models_yaml, key="slots")
    family = judges[judge_slot].family
    if family == models[model_slot].family:
        raise SameFamilyJudge(judge_slot, model_slot, family)


def sample_judgements(  # noqa: PLR0913, PLR0917 -- contract-shaped signature, see Interfaces above
    con: duckdb.DuckDBPyConnection,
    output_id: str,
    field: ItemField,
    observed: str,
    judge_slot: str,
    model_slot: str,
    *,
    n: int,
    seed: int,
    start: int = 0,
    resolve_fn: Callable[[str], Handle],
    call_fn: Callable[..., Response],
    context: CallContext,
    models_yaml: Path = Path("models.yaml"),
    sensitivity: Sensitivity = Sensitivity.SYNTHETIC,
) -> int:
    assert_judge_family_differs(judge_slot, model_slot, models_yaml)
    # The judge reads the same material the model under test read, so it needs the same
    # data-policy clearance -- checked before the judge is resolved, let alone called.
    assert_slot_may_see(
        judge_slot, sensitivity, load_slots(models_yaml, key="judge_slots"), models_yaml
    )
    handle = resolve_fn(judge_slot)
    if handle.is_fallback:
        raise ValueError(
            f"judge slot {judge_slot!r} resolved to a deterministic fallback handle. "
            "A fallback cannot judge; report the field type as not measured instead."
        )
    # `start` lets a resumed run top a partial target up: indices start..start+n-1 keep the
    # order seeds of already-stored samples from being repeated.
    for i in range(start, start + n):
        # audit: never Python's hash() here. str hashing is randomised per process
        # (PYTHONHASHSEED), so the presentation order would be irreproducible across runs and
        # judge_samples.presentation_order could never be regenerated -- which defeats both the
        # reproducibility test and spec 8.1's "randomised with a RECORDED seed".
        order_seed = int.from_bytes(
            hashlib.sha256(f"{output_id}:{field.field_name}:{i}".encode()).digest()[:4], "big"
        )
        presentation = randomise_presentation(field.expected_value, observed, seed=order_seed)
        payload = Labelled(
            value=build_judgement_prompt(field, presentation),
            sensitivity=sensitivity,
        )
        # Same two flags as the sweep: the judge's n>=3 samples are replicates, and a
        # failover would attribute one judge family's verdict to another -- which is
        # exactly the self-preference bias the family check exists to prevent.
        result = call_fn(
            handle,
            payload,
            context,
            cache=CacheMode.DISABLED,
            failover=FailoverMode.DISABLED,
        )
        con.execute(
            "INSERT INTO judge_samples VALUES (?,?,?,?,?,?,?,?)",
            [
                uuid.uuid4().hex,
                output_id,
                field.field_name,
                judge_slot,
                presentation.order,
                result.text,
                result.ledger_call_id,
                datetime.now(UTC),
            ],
        )
    return n


def run_judging(  # noqa: PLR0913 -- the sampler's contract plus the item set
    con: duckdb.DuckDBPyConnection,
    items: list[Item],
    rubric: dict[FieldType, RubricRule],
    *,
    n: int = 3,
    resolve_fn: Callable[[str], Handle],
    call_fn: Callable[..., Response],
    context: CallContext,
    models_yaml: Path = Path("models.yaml"),
    sensitivity: Sensitivity = Sensitivity.SYNTHETIC,
) -> int:
    """Sample each slot's judge n times on the modal output per (item, slot): 300 x 6 x 3 =
    5,400 calls (spec 15). Targets already sampled by their judge are skipped, so an
    interrupted overnight run resumes rather than paying twice."""
    assignments = judge_assignments(models_yaml)  # fails closed before any call
    fields = {
        (item.item_id, f.field_name): f
        for item in items
        for f in item.fields
        if rubric[f.field_type].grader == "judge"
    }
    calls = 0
    for field_name in sorted({name for _, name in fields}):
        for target in select_judge_targets(con, field_name):
            item_field = fields.get((target.item_id, field_name))
            if item_field is None or target.observed is None:
                continue
            judge = assignments[target.model_slot]
            done = con.execute(
                "SELECT count(*) FROM judge_samples WHERE output_id = ? AND field_name = ? "
                "AND judge_slot = ?",
                [target.output_id, field_name, judge],
            ).fetchone()
            have = 0 if done is None else int(done[0])
            if have >= n:
                continue
            calls += sample_judgements(
                con,
                target.output_id,
                item_field,
                target.observed,
                judge,
                target.model_slot,
                n=n - have,
                start=have,
                seed=0,  # inert: order seeds are hashed from output_id:field_name:index
                resolve_fn=resolve_fn,
                call_fn=call_fn,
                context=context,
                models_yaml=models_yaml,
                sensitivity=sensitivity,
            )
    return calls
