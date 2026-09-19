# tests/matrix/test_build.py
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ground_truth.golden.schema import Split
from ground_truth.graders.judge.aggregate import Sample
from ground_truth.graders.judge.agreement import JudgeStatus, assess, record_decision
from ground_truth.matrix.build import (
    LeaderboardRow,
    SlotSpecMissing,
    TokenCountsUnavailable,
    _slot_accuracy,
    build_leaderboard,
    distinguishability_statements,
)
from ground_truth.matrix.cost import LIST_PRICE_CAVEAT, cost_per_1k_items
from ground_truth.matrix.latency import summarise_latency
from ground_truth.providers import SlotSpec
from ground_truth.stats.bootstrap import Interval
from ground_truth.store.db import connect, migrate


def spec(slot: str) -> SlotSpec:
    return SlotSpec(
        slot=slot,
        family="fam",
        provider="prov",
        model_ref="ref",
        trains_on_data=False,
        commercial_use=True,
        exposes_fingerprint=False,
        list_price_in_per_1m=Decimal("0.10"),
        list_price_out_per_1m=Decimal("0.40"),
        pricing_url="https://example.invalid/p",
        retrieved_at=date(2026, 8, 31),
    )


def row(slot: str, low: float, point: float, high: float) -> LeaderboardRow:
    return LeaderboardRow(
        slot=slot,
        accuracy=Interval(point=point, low=low, high=high, n=180, method="cluster-BCa"),
        cost=cost_per_1k_items(spec(slot), 2000),
        latency=summarise_latency([100, 200, 300]),
        per_field={},
    )


def test_overlapping_rows_produce_a_plain_language_statement():
    statements = distinguishability_statements(
        [row("slot-a", 0.89, 0.92, 0.95), row("slot-b", 0.90, 0.93, 0.96)]
    )
    assert any("not distinguishable at this sample size" in s for s in statements)
    assert any("slot-a" in s and "slot-b" in s for s in statements)


def test_separated_rows_produce_no_statement():
    assert (
        distinguishability_statements(
            [row("slot-a", 0.60, 0.62, 0.64), row("slot-b", 0.90, 0.93, 0.96)]
        )
        == []
    )


def test_statement_carries_the_sample_size():
    statements = distinguishability_statements(
        [row("slot-a", 0.89, 0.92, 0.95), row("slot-b", 0.90, 0.93, 0.96)]
    )
    assert all("n=180" in s for s in statements)


def test_every_pair_is_examined():
    rows = [row("a", 0.89, 0.92, 0.95), row("b", 0.90, 0.93, 0.96), row("c", 0.91, 0.94, 0.97)]
    assert len(distinguishability_statements(rows)) == 3  # noqa: PLR2004


def test_single_row_produces_no_statements():
    assert distinguishability_statements([row("a", 0.89, 0.92, 0.95)]) == []


def test_rows_carry_the_cost_caveat():
    assert row("a", 0.89, 0.92, 0.95).cost.caveat == LIST_PRICE_CAVEAT


# -- build_leaderboard / the judge-rejection exclusion guarantee -----------------------
#
# COST (see ground_truth/matrix/build.py's module docstring): `outputs.token_count` is
# nullable -- rows written before that column existed, or written by a degraded-mode run
# with providers disabled, carry no token count. `build_leaderboard` raises
# `TokenCountsUnavailable` for any such slot rather than reporting a fabricated cost; once a
# slot's outputs do carry token counts, it computes a real `CostClaim` via
# `cost_per_1k_items`'s blended rate. Both paths are exercised below.
#
# The exclusion-join logic itself -- the actual guarantee this task exists to enforce -- is
# fully implemented and real (`_slot_accuracy`, which `build_leaderboard` calls first). The
# tests below prove: (1) that logic excludes a rejected field type's verdicts from the
# accuracy that would become the headline number, on the real query against a real store,
# and (2) `build_leaderboard` fails loudly rather than silently shipping a fabricated cost
# when token counts are missing, and (3) it produces a real cost when they are present.


def _populate_two_field_types(
    con, *, rejected_status: str | None, token_count: int | None = None
) -> None:
    """One item, one slot, one run, two field types (`money`, `date`) each graded once.
    `rejected_status` controls whether `money` carries a judge_decisions row and what its
    status is; `date` never gets one, so it always survives the exclusion join.
    `token_count` defaults to NULL -- the pre-migration / degraded-mode case."""
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES ('i1', 'public', 'v1', 'synthetic', 'h', now())"
    )
    con.execute("INSERT INTO item_fields VALUES ('i1', 'total', 'money', '1.00', NULL, NULL)")
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'invoice_date', 'date', '2026-01-01', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO runs VALUES ('r1', now(), NULL, 'slot-a', 'ref', 'prov', false, 's1',"
        " 'sha', 'h')"
    )
    con.execute(
        "INSERT INTO outputs VALUES ('o1', 'r1', 'i1', 1, '{}', 'call1', 'prov', NULL, 100,"
        " 'ph', now(), ?)",
        [token_count],
    )
    con.execute(
        "INSERT INTO verdicts VALUES ('v1', 'o1', 'total', 'exact', '1', 'v1', true, 'ok', now())"
    )
    con.execute(
        "INSERT INTO verdicts VALUES ('v2', 'o1', 'invoice_date', 'exact', '1', 'v1', true,"
        " 'ok', now())"
    )
    if rejected_status is not None:
        con.execute(
            "INSERT INTO judge_decisions VALUES ('money', 'v1', 0.5, 0.3, 0.7, 60, 0.667, ?,"
            " now())",
            [rejected_status],
        )


@pytest.fixture()
def con(tmp_path: Path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def test_rejected_field_type_is_absent_from_headline_accuracy(con):
    _populate_two_field_types(con, rejected_status="rejected")
    result = _slot_accuracy(con, split=Split.PUBLIC, seed=1)
    per_field = result["slot-a"].per_field
    assert "money" not in per_field, "a rejected judge's verdicts reached the headline number"
    assert "date" in per_field, "an undecided field type must not be swept up in the exclusion"


def test_accepted_field_type_is_not_excluded(con):
    _populate_two_field_types(con, rejected_status="accepted")
    result = _slot_accuracy(con, split=Split.PUBLIC, seed=1)
    per_field = result["slot-a"].per_field
    assert "money" in per_field and "date" in per_field


def test_latency_counts_each_output_once_not_once_per_graded_field(con):
    """Review finding (task-31): `records` has one row per verdict, so an output with two
    graded fields (money, date) surviving exclusion must still contribute exactly one
    latency observation, not two -- otherwise n and the percentiles are inflated for every
    multi-field item, which is the normal case for this domain, not an edge case."""
    _populate_two_field_types(con, rejected_status=None)
    result = _slot_accuracy(con, split=Split.PUBLIC, seed=1)
    assert result["slot-a"].latency.n == 1


def test_build_leaderboard_refuses_to_fabricate_cost(con):
    _populate_two_field_types(con, rejected_status=None, token_count=None)
    with pytest.raises(TokenCountsUnavailable):
        build_leaderboard(con, split=Split.PUBLIC, seed=1, specs={"slot-a": spec("slot-a")})


def test_build_leaderboard_reports_missing_spec_clearly(con):
    """A slot present in the store (with real token counts) but absent from `specs` --
    e.g. renamed or retired in models.yaml -- must fail with a documented error, not a bare
    KeyError (cross-file tracer finding)."""
    _populate_two_field_types(con, rejected_status=None, token_count=2000)
    with pytest.raises(SlotSpecMissing):
        build_leaderboard(con, split=Split.PUBLIC, seed=1, specs={})


def test_build_leaderboard_computes_real_cost_when_token_counts_present(con):
    _populate_two_field_types(con, rejected_status=None, token_count=2000)
    rows = build_leaderboard(con, split=Split.PUBLIC, seed=1, specs={"slot-a": spec("slot-a")})
    assert len(rows) == 1
    row_ = rows[0]
    assert row_.slot == "slot-a"
    assert row_.cost.value == cost_per_1k_items(spec("slot-a"), 2000).value
    assert "date" in row_.per_field


# -- Task 27's writer wired into Task 31's reader --------------------------------------
#
# Every judge_decisions row above is a hand-written fixture, which is exactly how the gap
# survived review: `assess` computed a status and nothing ever persisted it, so against real
# data the exclusion join could only take its `jd.status IS NULL` branch and no judge was ever
# actually excluded. These two tests run the real `assess` -> `record_decision` ->
# `_slot_accuracy` chain, in both directions, so the guarantee holds end to end.


def _judge_samples(n: int = 20) -> list[Sample]:
    return [
        Sample(presentation_order=i % 2, raw="EQUIVALENT", observed_length=10 + i) for i in range(n)
    ]


def _decide(con, *, agree: bool):
    """Assess a real judge-vs-human disagreement for field type `money`, and persist it."""
    judge = {str(i): "EQUIVALENT" for i in range(60)}
    if agree:
        human = {str(i): "EQUIVALENT" if i % 3 else "NOT_EQUIVALENT" for i in range(60)}
        judge = dict(human)
    else:
        human = {str(i): "EQUIVALENT" if i % 2 else "NOT_EQUIVALENT" for i in range(60)}
    report = assess("money", judge, human, _judge_samples(), seed=1, n_resamples=200)
    record_decision(con, report, rubric_version="v1")
    return report


def test_a_persisted_rejection_actually_excludes_that_field_type(con):
    _populate_two_field_types(con, rejected_status=None)
    report = _decide(con, agree=False)
    assert report.status is JudgeStatus.REJECTED

    per_field = _slot_accuracy(con, split=Split.PUBLIC, seed=1)["slot-a"].per_field
    assert "money" not in per_field, (
        "assess() rejected this judge and record_decision() stored it, yet its verdicts still "
        "reached the headline number"
    )
    assert "date" in per_field


def test_a_persisted_acceptance_leaves_its_field_type_in(con):
    """The other direction, and the guard on the enum/CHECK case mismatch: `JudgeStatus`
    renders "ACCEPTED"/"REJECTED" but the column's CHECK and build.py's `!= 'rejected'` are
    both lowercase. Writing the enum verbatim raises on insert; writing the wrong case
    silently never matches the exclusion, which looks identical to this passing test unless
    the rejection case above is asserted too."""
    _populate_two_field_types(con, rejected_status=None)
    report = _decide(con, agree=True)
    assert report.status is JudgeStatus.ACCEPTED

    stored = con.execute("SELECT status FROM judge_decisions WHERE field_type = 'money'").fetchone()
    assert stored == ("accepted",), "judge_decisions.status must be stored lowercase"

    per_field = _slot_accuracy(con, split=Split.PUBLIC, seed=1)["slot-a"].per_field
    assert "money" in per_field and "date" in per_field


def test_re_deciding_a_field_type_replaces_rather_than_raising(con):
    """`field_type` is the primary key: a second assessment (more labels, a re-run) must
    update the standing decision, not fail on a duplicate key."""
    _populate_two_field_types(con, rejected_status=None)
    _decide(con, agree=True)
    _decide(con, agree=False)
    rows = con.execute("SELECT status FROM judge_decisions WHERE field_type = 'money'").fetchall()
    assert rows == [("rejected",)]
