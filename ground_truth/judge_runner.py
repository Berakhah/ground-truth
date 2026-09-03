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
from ground_truth.golden.schema import ItemField
from ground_truth.policy import assert_slot_may_see
from ground_truth.providers import load_slots


class SameFamilyJudge(RuntimeError):
    def __init__(self, judge_slot: str, model_slot: str, family: str) -> None:
        super().__init__(
            f"judge {judge_slot!r} and model under test {model_slot!r} share family {family!r}; "
            "self-preference bias makes this judgement indefensible"
        )


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
    for i in range(n):
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
