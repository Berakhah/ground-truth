# ground_truth/matrix/build.py
"""Leaderboard rows: cluster-bootstrapped accuracy intervals per slot, judge verdicts counted
only for a judge with an accepted decision on that field type, plus the "not distinguishable
at this sample size" statement --
spec's brand behaviour and this task's whole reason to exist.

COST -- read before touching this: `outputs.token_count` (ground_truth/store/db.py) carries
one token total per call, not an input/output split -- the real bok-core ledger
(backoffice-kit/docs/INTERFACE-CONTRACT.md sec 3.4) only stores a single `tokens` column
too, so there is no split to recover even once that substrate is wired up for real.
`cost_per_1k_items` (ground_truth/matrix/cost.py) therefore prices the mean token count at a
*blended* rate -- the average of the spec's published input and output list price -- rather
than guessing a split, which would be exactly the fabrication CLAUDE.md rule 5 forbids.
`build_leaderboard` still raises `TokenCountsUnavailable` for any slot whose outputs carry no
token count at all (rows written before this column existed, or a degraded-mode run with
providers disabled) -- a missing number stays missing rather than becoming a silent zero.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

import duckdb

from ground_truth.golden.schema import Split
from ground_truth.matrix.cost import CostClaim, cost_per_1k_items
from ground_truth.matrix.latency import LatencyDistribution, summarise_latency
from ground_truth.providers import SlotSpec
from ground_truth.stats.bootstrap import Interval, cluster_bootstrap_ci


@dataclass(frozen=True)
class LeaderboardRow:
    slot: str
    accuracy: Interval
    cost: CostClaim
    latency: LatencyDistribution
    per_field: dict[str, Interval]


class TokenCountsUnavailable(RuntimeError):
    """Raised by build_leaderboard instead of fabricating a CostClaim. See the module
    docstring's COST section."""


class SlotSpecMissing(RuntimeError):
    """Raised by build_leaderboard when the store has real data for a slot that the
    supplied specs (models.yaml) no longer lists."""


# A `judge:<judge_slot>` verdict counts only when that judge has an accepted decision for that
# field type: no decision (unassessed), a rejection, or another judge's acceptance all keep it
# out. A deterministic verdict is never gated by a decision -- a rejected judge falls back to
# deterministic grading where one exists (docs/analysis-plan.md, "Judge rejection threshold").
# The join is on the full key `(field_type, judge_slot)`, so it matches at most one decision
# row and cannot fan a verdict out into several observations.
_OBSERVATIONS_SQL = """
    SELECT r.model_slot, o.output_id, o.item_id, ifld.field_type, v.correct, o.latency_ms,
           o.token_count
    FROM verdicts v
    JOIN outputs o ON o.output_id = v.output_id
    JOIN runs r ON r.run_id = o.run_id
    JOIN items i ON i.item_id = o.item_id
    JOIN item_fields ifld ON ifld.item_id = o.item_id AND ifld.field_name = v.field_name
    LEFT JOIN judge_decisions jd
           ON jd.field_type = ifld.field_type
          AND v.grader_id = 'judge:' || jd.judge_slot
    WHERE i.split = ? AND i.retired_at IS NULL
          AND (v.grader_id NOT LIKE 'judge:%' OR jd.status = 'accepted')
"""


@dataclass(frozen=True)
class _SlotAccuracy:
    accuracy: Interval
    per_field: dict[str, Interval]
    latency: LatencyDistribution
    mean_tokens: int | None


def _slot_accuracy(
    con: duckdb.DuckDBPyConnection, *, split: Split, seed: int
) -> dict[str, _SlotAccuracy]:
    """The exclusion-join, grouping, and bootstrap logic -- everything build_leaderboard
    needs, cost included. Kept separate so it is directly testable without needing a full
    build_leaderboard() call for every case."""
    by_slot: dict[str, list[tuple[str, str, str, bool, int, int | None]]] = defaultdict(list)
    for slot, output_id, item_id, field_type, correct, latency_ms, token_count in con.execute(
        _OBSERVATIONS_SQL, [split.value]
    ).fetchall():
        by_slot[slot].append(
            (output_id, item_id, field_type, bool(correct), int(latency_ms), token_count)
        )

    result: dict[str, _SlotAccuracy] = {}
    for slot in sorted(by_slot):
        records = by_slot[slot]
        overall = [(item_id, correct) for _, item_id, _, correct, _, _ in records]
        field_types = sorted({field_type for _, _, field_type, _, _, _ in records})
        per_field = {
            field_type: cluster_bootstrap_ci(
                [
                    (item_id, correct)
                    for _, item_id, ft, correct, _, _ in records
                    if ft == field_type
                ],
                seed=seed,
            )
            for field_type in field_types
        }
        # One latency/token observation per output, not per graded field: `records` has one
        # row per verdict, so an output with k graded fields would otherwise be counted k
        # times (review finding, task-31). All verdicts for the same output_id share one
        # latency_ms/token_count, so keying a dict by output_id collapses the fan-out
        # correctly. Single pass over `records` for both -- it can run to tens of thousands
        # of rows per slot (review finding).
        latency_by_output: dict[str, int] = {}
        tokens_by_output: dict[str, int] = {}
        for output_id, _, _, _, latency_ms, token_count in records:
            latency_by_output[output_id] = latency_ms
            if token_count is not None:
                tokens_by_output[output_id] = token_count
        mean_tokens = (
            round(sum(tokens_by_output.values()) / len(tokens_by_output))
            if tokens_by_output
            else None
        )
        result[slot] = _SlotAccuracy(
            accuracy=cluster_bootstrap_ci(overall, seed=seed),
            per_field=per_field,
            latency=summarise_latency(list(latency_by_output.values())),
            mean_tokens=mean_tokens,
        )
    return result


def build_leaderboard(
    con: duckdb.DuckDBPyConnection, *, split: Split, seed: int, specs: dict[str, SlotSpec]
) -> list[LeaderboardRow]:
    rows: list[LeaderboardRow] = []
    for slot, slot_accuracy in _slot_accuracy(con, split=split, seed=seed).items():
        if slot_accuracy.mean_tokens is None:
            raise TokenCountsUnavailable(
                f"cannot compute a real cost for slot {slot!r}: no output in the store for "
                "this slot/split carries a token count. See this module's COST note."
            )
        if slot not in specs:
            # A slot the store has real data for but models.yaml no longer lists -- a
            # renamed or retired slot, exactly the "models change silently behind stable
            # names" case this project exists to catch. A bare KeyError here would read as
            # an internal bug rather than the real, actionable cause.
            raise SlotSpecMissing(
                f"slot {slot!r} has accuracy data in the store but no entry in the supplied "
                "specs (models.yaml); it may have been renamed or retired there."
            )
        rows.append(
            LeaderboardRow(
                slot=slot,
                accuracy=slot_accuracy.accuracy,
                cost=cost_per_1k_items(specs[slot], slot_accuracy.mean_tokens),
                latency=slot_accuracy.latency,
                per_field=slot_accuracy.per_field,
            )
        )
    return rows


def distinguishability_statements(rows: list[LeaderboardRow]) -> list[str]:
    statements: list[str] = []
    for a, b in combinations(rows, 2):
        if a.accuracy.overlaps(b.accuracy):
            statements.append(
                f"{a.slot} and {b.slot} are not distinguishable at this sample size: "
                f"{a.accuracy.point:.3f} [{a.accuracy.low:.3f}, {a.accuracy.high:.3f}] versus "
                f"{b.accuracy.point:.3f} [{b.accuracy.low:.3f}, {b.accuracy.high:.3f}], "
                f"n={a.accuracy.n}."
            )
    return statements
