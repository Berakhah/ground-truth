"""python -m ground_truth.schedule --sweep-id <id> [--dry-run]

Batches the still-owed work for a sweep and, unless --dry-run, dispatches it. 9,000 calls
(300 golden items x 6 slots x 5 replicates, CLAUDE.md rule 6's n>=5) will not complete in
one run against free-tier limits, so this reads live quota via `remaining()` -- the shim's
stand-in for `bok_core.gateway.governor.remaining`, contract section 3.3 -- at plan time
rather than trusting a stale static table, and prints both the quota and when it was
fetched so a plan built against yesterday's limits is visible as such.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from ground_truth._bok_shim import Quota, remaining
from ground_truth.golden.schema import FieldType, Item, ItemField, Source, Split
from ground_truth.providers import load_slots
from ground_truth.runner import execute_sweep, pending_work
from ground_truth.store.db import connect, migrate

REPO = Path(__file__).resolve().parent.parent
MODELS_YAML = REPO / "models.yaml"
CORPUS = REPO / "golden" / "corpus"

# 300 golden items (120 public + 180 private, see golden/build.py) x 6 slots x 5 replicates
# = 9,000 calls, the number this task opens with. CLAUDE.md rule 6: n>=5 per item, always.
REPLICATES = 5


@dataclass(frozen=True)
class WorkUnit:
    sweep_id: str
    slot: str
    item_id: str
    replicate_idx: int


def plan_batches(
    units: list[WorkUnit],
    quotas: dict[str, Quota],
    slot_providers: dict[str, str],
    *,
    tokens_per_call: dict[str, int] | None = None,
    daily_token_budget: dict[str, int] | None = None,
) -> list[list[WorkUnit]]:
    """Group by provider, then pack each provider's units into days of its daily pool.

    A "day" is bounded by the provider's `rpd` (calls) and, when `daily_token_budget` names
    the provider, by its tokens/day too (Groq: 1K RPD but 200K TPD, so tokens bind first).
    `Quota` carries no token-per-day field, hence the separate arguments; the per-slot
    `tokens_per_call` comes from the Phase 0/1 probe, never a guess. Slots on one provider
    share one pool (conservative: if a provider limits per model, this over-plans days, it
    never 429s). Batches are cut at day boundaries and never mix slots, so consecutive
    batches of a provider fill a day until the next batch starts one.

    `slot_providers[slot]`, `quotas[provider]` and `tokens_per_call[slot]` (when the provider
    has a token budget) raise KeyError on anything unconfigured rather than defaulting
    silently. `rpd is None` means the provider does not publish a daily limit and is treated
    as unbounded, never as zero (Quota's contract, section 3.3). A call that cannot fit an
    empty day raises ValueError rather than looping forever.
    """
    tokens_per_call = tokens_per_call or {}
    daily_token_budget = daily_token_budget or {}

    by_provider: dict[str, dict[str, list[WorkUnit]]] = {}
    for unit in units:
        provider = slot_providers[unit.slot]
        by_provider.setdefault(provider, {}).setdefault(unit.slot, []).append(unit)

    batches: list[list[WorkUnit]] = []
    for provider, slots in by_provider.items():
        rpd = quotas[provider].rpd
        if rpd is not None and rpd <= 0:
            continue  # a real, published zero-call ceiling: nothing fits today
        budget = daily_token_budget.get(provider)
        calls_today = tokens_today = 0
        for slot, slot_units in slots.items():
            cost = tokens_per_call[slot] if budget is not None else 0
            if budget is not None and cost > budget:
                raise ValueError(f"{slot}: one call ({cost} tokens) can never fit {budget}/day")
            current: list[WorkUnit] = []
            for unit in slot_units:
                full = (rpd is not None and calls_today + 1 > rpd) or (
                    budget is not None and tokens_today + cost > budget
                )
                if full:
                    if current:
                        batches.append(current)
                        current = []
                    calls_today = tokens_today = 0
                current.append(unit)
                calls_today += 1
                tokens_today += cost
            if current:
                batches.append(current)
    return batches


def _load_items(con: duckdb.DuckDBPyConnection, corpus_dir: Path = CORPUS) -> list[Item]:
    """The corpus `golden.build` already wrote, read back for a sweep. Scheduling plans
    against the persisted corpus, never regenerates it -- build.py's seeds are secret
    precisely so the private split can't be recovered.

    Fields come from `item_fields` in insertion order (the order `build_prompt` lists the
    keys in). The DB stores no `layout`, so the document the model sees is the corpus file
    itself, read verbatim; a missing file raises FileNotFoundError rather than letting a
    prompt go out with no document.
    """
    fields: dict[str, list[ItemField]] = {}
    for item_id, name, ftype, expected, normalised, tolerance in con.execute(
        "SELECT item_id, field_name, field_type, expected_value, expected_normalised, tolerance "
        "FROM item_fields ORDER BY rowid"
    ).fetchall():
        fields.setdefault(item_id, []).append(
            ItemField(
                field_name=name,
                field_type=FieldType(ftype),
                expected_value=expected,
                expected_normalised=normalised,
                tolerance=Decimal(tolerance) if tolerance is not None else None,
            )
        )
    return [
        Item(
            item_id=item_id,
            split=Split(split),
            rubric_version=rubric_version,
            source=Source(source),
            content_hash=content_hash,
            fields=fields.get(item_id, []),
            document=(corpus_dir / split / f"{item_id}.txt").read_text(encoding="utf-8"),
        )
        for item_id, split, rubric_version, source, content_hash in con.execute(
            "SELECT item_id, split, rubric_version, source, content_hash FROM items"
        ).fetchall()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan and, unless --dry-run, run a sweep's pending work."
    )
    parser.add_argument("--sweep-id", required=True, help="Sweep id to start or resume.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; call no provider.")
    args = parser.parse_args()

    slots = load_slots(MODELS_YAML)
    slot_providers = {name: spec.provider for name, spec in slots.items()}

    quotas: dict[str, Quota] = {}
    for provider in sorted(set(slot_providers.values())):
        retrieved_at = datetime.now(UTC)
        quota = remaining(provider)
        quotas[provider] = quota
        print(f"quota[{provider}] = {quota!r}  (retrieved {retrieved_at.isoformat()})")

    con = connect(REPO / "data" / "results.duckdb")
    migrate(con)
    try:
        items = _load_items(con)
        units = pending_work(con, args.sweep_id, items, list(slot_providers), REPLICATES)
        batches = plan_batches(units, quotas, slot_providers)
        for i, batch in enumerate(batches):
            slot = batch[0].slot
            print(f"batch {i}: slot={slot} provider={slot_providers[slot]} n={len(batch)}")
        print(f"total pending calls: {len(units)}")

        if args.dry_run:
            return

        # Deferred: bok_core is the real gateway package, not installed in this scaffold
        # repo (ground_truth._bok_shim stands in for it everywhere else). Importing it only
        # here means --dry-run keeps working without it, and a live run fails loudly and
        # immediately if it's still missing, rather than pretending to dispatch calls.
        from bok_core.gateway.lanes import (  # type: ignore[import-not-found]  # noqa: PLC0415
            resolve,
        )
        from bok_core.gateway.router import (  # type: ignore[import-not-found]  # noqa: PLC0415
            call,
        )

        from ground_truth._bok_shim import CallContext  # noqa: PLC0415

        # `sweep_id=args.sweep_id` is what makes --sweep-id mean anything past the plan
        # printed above: without it execute_sweep minted its own id, so `pending_work` found
        # nothing recorded under the id it was asked to resume and the whole sweep was
        # re-spent on every restart (audit H9, the bug Task 23 exists to fix).
        execute_sweep(
            con,
            items,
            list(slot_providers),
            REPLICATES,
            context=CallContext(),
            resolve_fn=resolve,
            call_fn=call,
            sweep_id=args.sweep_id,
        )
    finally:
        con.close()


if __name__ == "__main__":
    main()
