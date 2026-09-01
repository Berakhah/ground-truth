# ground_truth/matrix/build.py
"""Leaderboard rows: cluster-bootstrapped accuracy intervals per slot, judge-rejected
field types excluded, plus the "not distinguishable at this sample size" statement --
spec's brand behaviour and this task's whole reason to exist.

KNOWN GAP -- read before touching cost: `outputs`/`runs` (ground_truth/store/db.py) do not
record token counts anywhere, and neither does the bok-core shim's Response
(ground_truth/_bok_shim.py) or runner.execute_sweep's INSERT statements that populate those
tables from it -- checked end to end. `cost_per_1k_items` (ground_truth/matrix/cost.py)
itself refuses non-positive token counts ("a zero cost would be a fabrication"), so there is
no way to give it real numbers here without either a schema change beyond the
`judge_decisions` table this task was authorised to add, or fabricating a token count that
would show up in a `CostClaim.value` looking like real data -- the exact failure CLAUDE.md
rule 5 exists to prevent. Task 31's own brief flagged this as a likely gap and said to
escalate rather than invent (see task-31-report.md). `build_leaderboard` therefore raises
`TokenCountsUnavailable` at the cost step instead of guessing; `_slot_accuracy` carries the
real, tested accuracy/per-field/exclusion/latency logic and is what `build_leaderboard`
will wire cost onto once token-count storage exists.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

import duckdb

from ground_truth.golden.schema import Split
from ground_truth.matrix.cost import (  # noqa: F401 -- see module docstring
    CostClaim,
    cost_per_1k_items,
)
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
    docstring's KNOWN GAP section."""


_OBSERVATIONS_SQL = """
    SELECT r.model_slot, o.item_id, ifld.field_type, v.correct, o.latency_ms
    FROM verdicts v
    JOIN outputs o ON o.output_id = v.output_id
    JOIN runs r ON r.run_id = o.run_id
    JOIN items i ON i.item_id = o.item_id
    JOIN item_fields ifld ON ifld.item_id = o.item_id AND ifld.field_name = v.field_name
    LEFT JOIN judge_decisions jd ON jd.field_type = ifld.field_type
    WHERE i.split = ? AND (jd.status IS NULL OR jd.status != 'rejected')
"""


@dataclass(frozen=True)
class _SlotAccuracy:
    accuracy: Interval
    per_field: dict[str, Interval]
    latency: LatencyDistribution


def _slot_accuracy(
    con: duckdb.DuckDBPyConnection, *, split: Split, seed: int
) -> dict[str, _SlotAccuracy]:
    """The exclusion-join, grouping, and bootstrap logic -- everything build_leaderboard
    needs except cost. Kept separate so it is directly testable without a real per-run
    token count (see TokenCountsUnavailable)."""
    by_slot: dict[str, list[tuple[str, str, bool, int]]] = defaultdict(list)
    for slot, item_id, field_type, correct, latency_ms in con.execute(
        _OBSERVATIONS_SQL, [split.value]
    ).fetchall():
        by_slot[slot].append((item_id, field_type, bool(correct), int(latency_ms)))

    result: dict[str, _SlotAccuracy] = {}
    for slot in sorted(by_slot):
        records = by_slot[slot]
        overall = [(item_id, correct) for item_id, _, correct, _ in records]
        field_types = sorted({field_type for _, field_type, _, _ in records})
        per_field = {
            field_type: cluster_bootstrap_ci(
                [(item_id, correct) for item_id, ft, correct, _ in records if ft == field_type],
                seed=seed,
            )
            for field_type in field_types
        }
        result[slot] = _SlotAccuracy(
            accuracy=cluster_bootstrap_ci(overall, seed=seed),
            per_field=per_field,
            latency=summarise_latency([latency_ms for _, _, _, latency_ms in records]),
        )
    return result


def build_leaderboard(
    con: duckdb.DuckDBPyConnection, *, split: Split, seed: int, specs: dict[str, SlotSpec]
) -> list[LeaderboardRow]:
    rows: list[LeaderboardRow] = []
    for slot, acc in _slot_accuracy(con, split=split, seed=seed).items():
        del acc  # would feed LeaderboardRow(...) once cost is unblocked; see module docstring
        raise TokenCountsUnavailable(
            f"cannot compute a real cost for slot {slot!r}: no run in the store carries a "
            "token count. See TokenCountsUnavailable's docstring / this module's KNOWN GAP."
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
