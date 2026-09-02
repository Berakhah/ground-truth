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
from pathlib import Path

import duckdb

from ground_truth._bok_shim import Quota, remaining
from ground_truth.golden.schema import Item, Source, Split
from ground_truth.providers import load_slots
from ground_truth.runner import execute_sweep, pending_work
from ground_truth.store.db import connect, migrate

REPO = Path(__file__).resolve().parent.parent
MODELS_YAML = REPO / "models.yaml"

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
) -> list[list[WorkUnit]]:
    """Group by slot, then chunk each group to its provider's daily ceiling.

    `slot_providers[slot]` and `quotas[provider]` raise KeyError on anything unconfigured
    rather than defaulting silently -- planning against a guessed provider risks 429s the
    caller never sees coming. `rpd is None` means the provider does not publish a daily
    limit and is treated as unbounded, never as zero (Quota's contract, section 3.3).
    Batches from different providers stay separate list entries so an overnight run can
    interleave them instead of draining one provider before starting the next.
    """
    grouped: dict[str, list[WorkUnit]] = {}
    for unit in units:
        grouped.setdefault(unit.slot, []).append(unit)

    batches: list[list[WorkUnit]] = []
    for slot, slot_units in grouped.items():
        provider = slot_providers[slot]
        rpd = quotas[provider].rpd
        chunk = rpd if rpd is not None else len(slot_units)
        if chunk <= 0:
            continue  # a real, published zero-call ceiling: nothing fits today
        for start in range(0, len(slot_units), chunk):
            batches.append(slot_units[start : start + chunk])
    return batches


def _load_items(con: duckdb.DuckDBPyConnection) -> list[Item]:
    """The corpus `golden.build` already wrote to `items`. Scheduling plans against the
    persisted corpus, never regenerates it -- build.py's seeds are secret precisely so the
    private split can't be recovered, and pending_work/plan_batches only ever read
    `item.item_id`.

    ponytail: fields=[] below, not joined from `item_fields` -- planning and (Step 6, out of
    scope here) live dispatch never inspect them; build_prompt does. Join item_fields into
    real ItemField rows here before this main() is ever used for a live, non-dry-run sweep.
    """
    return [
        Item(
            item_id=item_id,
            split=Split(split),
            rubric_version=rubric_version,
            source=Source(source),
            content_hash=content_hash,
            fields=[],
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
