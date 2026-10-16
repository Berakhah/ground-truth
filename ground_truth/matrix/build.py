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
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

import duckdb

from ground_truth.golden.schema import Split
from ground_truth.graders.judge.targets import select_judge_targets
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
# out. A decision never gates a deterministic verdict by itself -- a rejected judge falls back to
# deterministic grading where one exists (docs/analysis-plan.md, "Judge rejection threshold").
# Only a judge that counts displaces them: judge wins on its field type (JP-1, see
# `_headline_observations`).
# The join is on the full key `(field_type, judge_slot)`, so it matches at most one decision
# row and cannot fan a verdict out into several observations.
#
# Re-grades. `verdicts` is append-only: a re-grade at a bumped grader or rubric version, or after
# the rubric moved a field type to another grader, appends verdicts beside the old ones. The
# latest wins (computed_at, then the greater verdict_id on a tie), so each output contributes
# at most one deterministic verdict per field whichever deterministic grader wrote it (final
# review 2026-10-15, I1), and at most one verdict per judge per field -- a judge verdict is not
# superseded in this query by a deterministic one or by another judge's; the decision gate, the
# assigned-judge rule and "judge wins" in `_headline_observations` decide which of those counts.
#
# Schema. A deterministic verdict counts only while its output's latest `__schema__` verdict is
# correct (`_LATEST_SCHEMA_SQL`): grading writes no field verdict for an unparseable output, so
# after a re-grade that fails the schema check, that output's older field verdicts would still be
# the latest of their field (final review 2026-10-15, I2). A judge verdict is not gated on the
# schema: an unparseable modal target is judged, and scores, as absent.
_LATEST_SCHEMA_SQL = """
    latest_schema AS (
        SELECT output_id, correct
        FROM verdicts
        WHERE field_name = '__schema__'
        QUALIFY row_number() OVER (
            PARTITION BY output_id ORDER BY computed_at DESC, verdict_id DESC
        ) = 1
    )
"""

_OBSERVATIONS_SQL = f"""
    WITH {_LATEST_SCHEMA_SQL}
    SELECT v.verdict_id, r.model_slot, o.output_id, o.item_id, ifld.field_type, v.correct,
           o.latency_ms, o.token_count, v.grader_id, v.field_name
    FROM verdicts v
    JOIN outputs o ON o.output_id = v.output_id
    JOIN runs r ON r.run_id = o.run_id
    JOIN items i ON i.item_id = o.item_id
    JOIN item_fields ifld ON ifld.item_id = o.item_id AND ifld.field_name = v.field_name
    LEFT JOIN judge_decisions jd
           ON jd.field_type = ifld.field_type
          AND v.grader_id = 'judge:' || jd.judge_slot
    LEFT JOIN latest_schema s ON s.output_id = v.output_id
    WHERE i.split = ? AND i.retired_at IS NULL
          AND (v.grader_id NOT LIKE 'judge:%' OR jd.status = 'accepted')
          AND (v.grader_id LIKE 'judge:%' OR s.correct IS TRUE)
    QUALIFY row_number() OVER (
        PARTITION BY v.output_id, v.field_name,
                     CASE WHEN v.grader_id LIKE 'judge:%' THEN v.grader_id END
        ORDER BY v.computed_at DESC, v.verdict_id DESC
    ) = 1
"""


_JUDGE_PREFIX = "judge:"


def _current_judge_targets(
    con: duckdb.DuckDBPyConnection, field_names: set[str]
) -> set[tuple[str, str]]:
    """`(output_id, field_name)` for each current judge target: the modal output per (item,
    slot), selected exactly as grading selects it.

    The judge scores one output per (item, slot, field). Outputs added after a grading pass
    (more replicates, another run of the slot) can move the modal value to another output;
    grading then writes a verdict for the new target, and the old target's verdict stays in the
    append-only `verdicts` table. Counting only the current target's verdict keeps one judge
    observation per (item, slot, field) instead of two different judgements of it. A current
    target with no verdict yet from the slot's current judge has none to count, so the field
    is unjudged for that item rather than scored from a stale output.

    Cost: `select_judge_targets` reads and JSON-parses every output once per judged field
    name, both splits, on every build -- at 300 items x 6 slots x 5 replicates that is 9,000
    parses per field, cheap next to the bootstrap. If it ever is not, compute the targets once
    and share them with grading rather than caching a copy that could drift from it.
    """
    return {
        (target.output_id, field_name)
        for field_name in sorted(field_names)
        for target in select_judge_targets(con, field_name)
    }


def _judged_field_types_every_slot_holds(
    con: duckdb.DuckDBPyConnection, slots: set[str], judges: Mapping[str, str | None]
) -> frozenset[str]:
    """The field types a judge verdict may count on: every slot ranked in this split has an
    assigned judge, and that judge holds an accepted decision on the field type.

    With one judge per slot, gating each slot on its own judge alone ranked a slot whose judge
    was accepted on money + descriptions against one whose judge was not, on money alone --
    intervals over different field sets, compared in the "not distinguishable" statements
    without a word about it (final review 2026-10-14, I1). Failing closed for every slot
    together keeps one field set per leaderboard; the field falls back to deterministic
    grading where one exists, as for a rejected judge. `slots` is every slot with a verdict in
    the split, so a slot ranked on deterministic fields alone still takes part.
    """
    accepted: dict[str, set[str]] = defaultdict(set)
    for field_type, judge_slot in con.execute(
        "SELECT field_type, judge_slot FROM judge_decisions WHERE status = 'accepted'"
    ).fetchall():
        accepted[field_type].add(judge_slot)
    assigned = [judges.get(slot) for slot in slots]
    return frozenset(
        field_type
        for field_type, judge_slots in accepted.items()
        if all(judge is not None and judge in judge_slots for judge in assigned)
    )


@dataclass(frozen=True)
class _SlotAccuracy:
    accuracy: Interval
    per_field: dict[str, Interval]
    latency: LatencyDistribution
    mean_tokens: int | None


@dataclass(frozen=True)
class _Observation:
    verdict_id: str
    slot: str
    output_id: str
    item_id: str
    field_type: str
    correct: bool
    latency_ms: int
    token_count: int | None
    # How many observations this verdict stands for in the item's score. A deterministic
    # grader writes one verdict per replicate output, so each of its verdicts weighs 1. The
    # judge writes one verdict per (item, slot), on the modal output, so its verdict weighs the
    # (item, slot)'s count of outputs whose latest `__schema__` verdict is correct (floor 1):
    # the judged field then carries as much of the item's score as a deterministic field does,
    # however many runs the slot has and however often it was re-graded (final review
    # 2026-10-14, I2; 2026-10-15, I2). Applied by repeating the observation, so
    # `stats.bootstrap`'s flat per-item mean is unchanged.
    weight: int


# The judged field's weight: how many verdicts a deterministic field has for this (item, slot),
# i.e. the outputs whose latest `__schema__` verdict is correct -- the same set
# `_OBSERVATIONS_SQL` admits deterministic verdicts from. Counting every stored output let
# schema-invalid and not-yet-graded replicates inflate the judged field's share of the item
# score; counting any correct schema verdict ever kept an output re-graded as unparseable in
# the weight after its field verdicts had dropped out (final review 2026-10-15, I2).
_REPLICATES_SQL = f"""
    WITH {_LATEST_SCHEMA_SQL}
    SELECT o.item_id, r.model_slot, count(*)
    FROM outputs o
    JOIN runs r ON r.run_id = o.run_id
    JOIN latest_schema s ON s.output_id = o.output_id
    WHERE s.correct
    GROUP BY o.item_id, r.model_slot
"""


def _unjudged_field_types(
    con: duckdb.DuckDBPyConnection,
    *,
    split: Split,
    slots: set[str],
    judged: set[tuple[str, str]],
    field_types: set[str],
) -> frozenset[str]:
    """The judged field types with a current judge target that has no counted verdict yet.

    `judged` is `(output_id, field_name)` for every judge verdict that survived the other
    gates; `field_types` the judged types still in play. A target belongs to this split when its
    item is in the split, is not retired, and declares the field. A target is unjudged when it
    has no verdict yet from the slot's current judge on the current modal output: fewer than
    three samples (`judge_verdict` returns None), a reassigned judge that has not judged it, or
    a modal target that moved to an output not judged yet. Unjudged is not a measurement, so
    the type is held back for every slot until the sweep finishes it. An inconclusive or
    not-extracted verdict exists and so counts as judged.
    """
    if not field_types:
        return frozenset()
    declared = con.execute(
        "SELECT i.item_id, f.field_name, f.field_type FROM items i "
        "JOIN item_fields f ON f.item_id = i.item_id "
        "WHERE i.split = ? AND i.retired_at IS NULL",
        [split.value],
    ).fetchall()
    type_of = {(item_id, name): ftype for item_id, name, ftype in declared}
    names = sorted({name for (_, name), ftype in type_of.items() if ftype in field_types})
    return frozenset(
        type_of[(target.item_id, name)]
        for name in names
        for target in select_judge_targets(con, name)
        if (target.item_id, name) in type_of
        and target.model_slot in slots
        and (target.output_id, name) not in judged
    )


REASON_JUDGE_NOT_ACCEPTED = "not every ranked slot's judge holds an accepted decision on it"
REASON_JUDGING_INCOMPLETE = "judging incomplete: a current target has no verdict yet"


@dataclass(frozen=True)
class HeldBackFieldType:
    """A judged field type the headline leaves out, and why (JP-12).

    Published from the private split, so it is a type name and a fixed reason string and nothing
    else: no item, output, hash or count. Where the rubric has a deterministic grader for the
    type, the headline falls back to it; the type is still not scored by the judge.
    """

    field_type: str
    reason: str


def _headline_selection(
    con: duckdb.DuckDBPyConnection, *, split: Split, judges: Mapping[str, str | None]
) -> tuple[list[_Observation], list[HeldBackFieldType]]:
    """Every verdict the headline counts for `split` -- the one place that rule lives -- and the
    judged field types it left out as a whole (`HeldBackFieldType`).

    `_slot_accuracy` scores these and `headline_verdict_ids` exposes their ids, which the
    publisher writes as `counts_toward_headline` so a recompute from the published verdict
    files reaches the published number (review 2026-10-14, I3). On top of `_OBSERVATIONS_SQL`
    (the split, retired items, fields the item does not declare such as `__schema__`, the
    judge-decision gate, latest-wins on re-grades, and a deterministic verdict only from an
    output whose latest `__schema__` verdict is correct), a judge verdict counts only when:

    - it is on the current modal target (`_current_judge_targets`), and
    - it is from the slot's currently assigned judge. `judges` maps each model slot to that
      judge (models.yaml's `judge`). After a reassignment the old judge's verdicts on the same
      target stay in `verdicts`, and if both judges hold an accepted decision, counting both
      would weigh the field twice in the item's cluster mean with two judgements that can
      contradict (review 2026-10-14, I2). A slot with no assigned judge counts no judge
      verdict.
    - its field type is one every ranked slot's assigned judge holds an accepted decision on
      (`_judged_field_types_every_slot_holds`), and
    - its field type has no current judge target left unjudged in this split
      (`_unjudged_field_types`). While any target for it has no verdict yet (a sweep still
      running), the type is out for every slot: counting the judged items would rank one slot
      on more descriptions than another. It falls back to deterministic grading, as for a
      rejected judge. An inconclusive verdict is a measurement and counts as judged.
    """
    rows = con.execute(_OBSERVATIONS_SQL, [split.value]).fetchall()
    current_targets = _current_judge_targets(
        con, {row[9] for row in rows if row[8].startswith(_JUDGE_PREFIX)}
    )
    shared = _judged_field_types_every_slot_holds(con, {row[1] for row in rows}, judges)
    replicates = {
        (item_id, slot): int(count)
        for item_id, slot, count in con.execute(_REPLICATES_SQL).fetchall()
    }
    candidates: list[tuple[_Observation, str | None]] = []
    not_shared: set[str] = set()
    for (
        verdict_id,
        slot,
        output_id,
        item_id,
        field_type,
        correct,
        latency_ms,
        token_count,
        grader_id,
        field_name,
    ) in rows:
        if grader_id.startswith(_JUDGE_PREFIX):
            if (output_id, field_name) not in current_targets:
                continue  # a former modal target's judge verdict; see `_current_judge_targets`
            assigned = judges.get(slot)
            if assigned is None or grader_id != _JUDGE_PREFIX + assigned:
                continue  # not the slot's currently assigned judge
            if field_type not in shared:
                not_shared.add(field_type)
                continue  # some ranked slot's judge is not accepted on it: out for every slot
        candidates.append(
            (
                _Observation(
                    verdict_id=verdict_id,
                    slot=slot,
                    output_id=output_id,
                    item_id=item_id,
                    field_type=field_type,
                    correct=bool(correct),
                    latency_ms=int(latency_ms),
                    token_count=token_count,
                    weight=(
                        max(1, replicates.get((item_id, slot), 0))
                        if grader_id.startswith(_JUDGE_PREFIX)
                        else 1
                    ),
                ),
                field_name if grader_id.startswith(_JUDGE_PREFIX) else None,
            )
        )
    judged = {(o.output_id, name) for o, name in candidates if name is not None}
    held_back = _unjudged_field_types(
        con,
        split=split,
        slots={o.slot for o, _ in candidates},
        judged=judged,
        field_types={o.field_type for o, name in candidates if name is not None},
    )
    counted = [(o, name) for o, name in candidates if name is None or o.field_type not in held_back]
    # Judge wins (JP-1, decided 2026-10-15): a field type the judge counts on is scored by the
    # judge alone. A field the rubric moved from a deterministic grader to the judge keeps its
    # old deterministic verdicts in the append-only table; counting them beside the judge's
    # would score one field twice with two judgements that can contradict. Where the judge does
    # not count (rejected, unassessed, unassigned, held back) nothing is dropped, so the field
    # still falls back to deterministic grading.
    judged_types = {o.field_type for o, name in counted if name is not None}
    observations = [
        o for o, name in counted if name is not None or o.field_type not in judged_types
    ]
    # A type is either not shared (skipped above, never a candidate) or held back (a candidate
    # dropped just now), never both.
    left_out = [HeldBackFieldType(ft, REASON_JUDGE_NOT_ACCEPTED) for ft in not_shared] + [
        HeldBackFieldType(ft, REASON_JUDGING_INCOMPLETE) for ft in held_back
    ]
    return observations, sorted(left_out, key=lambda h: h.field_type)


def _headline_observations(
    con: duckdb.DuckDBPyConnection, *, split: Split, judges: Mapping[str, str | None]
) -> list[_Observation]:
    return _headline_selection(con, split=split, judges=judges)[0]


def held_back_field_types(
    con: duckdb.DuckDBPyConnection, *, split: Split, judges: Mapping[str, str | None]
) -> list[HeldBackFieldType]:
    """The judged field types the headline for `split` left out, sorted by name; see
    `_headline_selection`. The publisher writes these into `leaderboard.json` so a reader is
    told what the headline does not cover instead of inferring it from the field list."""
    return _headline_selection(con, split=split, judges=judges)[1]


def headline_verdict_weights(
    con: duckdb.DuckDBPyConnection, *, split: Split, judges: Mapping[str, str | None]
) -> dict[str, int]:
    """Each verdict the headline for `split` counts, by id, with its weight in its item's
    score; see `_headline_observations`. The publisher writes these as `counts_toward_headline`
    and `weight`, so a recompute from the published verdict files reaches the headline."""
    return {o.verdict_id: o.weight for o in _headline_observations(con, split=split, judges=judges)}


def headline_verdict_ids(
    con: duckdb.DuckDBPyConnection, *, split: Split, judges: Mapping[str, str | None]
) -> frozenset[str]:
    """The ids of the verdicts the headline for `split` counts; see `_headline_observations`."""
    return frozenset(headline_verdict_weights(con, split=split, judges=judges))


def _slot_accuracy(
    con: duckdb.DuckDBPyConnection,
    *,
    split: Split,
    seed: int,
    judges: Mapping[str, str | None],
) -> dict[str, _SlotAccuracy]:
    """The grouping and bootstrap logic over `_headline_observations` -- everything
    build_leaderboard needs, cost included. Kept separate so it is directly testable without
    needing a full build_leaderboard() call for every case."""
    by_slot: dict[str, list[tuple[str, str, str, bool, int, int | None]]] = defaultdict(list)
    for o in _headline_observations(con, split=split, judges=judges):
        # `weight` copies of one observation: the flat per-item mean in `stats.bootstrap` then
        # weighs it `weight` times. Latency and tokens are keyed by output below, so the copies
        # add no latency or token observation.
        by_slot[o.slot].extend(
            [(o.output_id, o.item_id, o.field_type, o.correct, o.latency_ms, o.token_count)]
            * o.weight
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
    judges = {name: spec.judge for name, spec in specs.items()}
    for slot, slot_accuracy in _slot_accuracy(con, split=split, seed=seed, judges=judges).items():
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
