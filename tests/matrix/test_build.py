# tests/matrix/test_build.py
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ground_truth.golden.schema import Split
from ground_truth.matrix.build import (
    LeaderboardRow,
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
    return SlotSpec(slot=slot, family="fam", provider="prov", model_ref="ref",
                    trains_on_data=False, commercial_use=True, exposes_fingerprint=False,
                    list_price_in_per_1m=Decimal("0.10"), list_price_out_per_1m=Decimal("0.40"),
                    pricing_url="https://example.invalid/p", retrieved_at=date(2026, 8, 31))


def row(slot: str, low: float, point: float, high: float) -> LeaderboardRow:
    return LeaderboardRow(
        slot=slot,
        accuracy=Interval(point=point, low=low, high=high, n=180, method="cluster-BCa"),
        cost=cost_per_1k_items(spec(slot), 2000, 500),
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
    assert distinguishability_statements(
        [row("slot-a", 0.60, 0.62, 0.64), row("slot-b", 0.90, 0.93, 0.96)]
    ) == []


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
# KNOWN GAP (see ground_truth/matrix/build.py's module docstring): `outputs`/`runs` do not
# record token counts anywhere in the schema, so `build_leaderboard` cannot produce a real,
# non-fabricated `CostClaim` -- `LeaderboardRow.cost` is a required field, and
# `cost_per_1k_items` itself refuses non-positive token counts. Task 31's brief said to
# escalate this rather than add schema beyond `judge_decisions` or invent a token count, so
# `build_leaderboard` raises `TokenCountsUnavailable` at the cost step instead of guessing.
#
# The exclusion-join logic itself -- the actual guarantee this task exists to enforce -- is
# fully implemented and real (`_slot_accuracy`, which `build_leaderboard` calls first). The
# tests below prove: (1) that logic excludes a rejected field type's verdicts from the
# accuracy that would become the headline number, on the real query against a real store,
# and (2) `build_leaderboard` fails loudly rather than silently shipping a fabricated cost
# once accuracy is ready to be reported. Once token-count storage exists, wiring
# `_slot_accuracy`'s output into `LeaderboardRow.cost` is the one remaining line.


def _populate_two_field_types(con, *, rejected_status: str | None) -> None:
    """One item, one slot, one run, two field types (`money`, `date`) each graded once.
    `rejected_status` controls whether `money` carries a judge_decisions row and what its
    status is; `date` never gets one, so it always survives the exclusion join."""
    con.execute(
        "INSERT INTO items VALUES ('i1', 'public', 'v1', 'synthetic', 'h', now())"
    )
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'total', 'money', '1.00', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'invoice_date', 'date', '2026-01-01', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO runs VALUES ('r1', now(), NULL, 'slot-a', 'ref', 'prov', false, 's1',"
        " 'sha', 'h')"
    )
    con.execute(
        "INSERT INTO outputs VALUES ('o1', 'r1', 'i1', 1, '{}', 'call1', 'prov', NULL, 100,"
        " 'ph', now())"
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


def test_build_leaderboard_refuses_to_fabricate_cost(con):
    _populate_two_field_types(con, rejected_status=None)
    with pytest.raises(TokenCountsUnavailable):
        build_leaderboard(con, split=Split.PUBLIC, seed=1, specs={"slot-a": spec("slot-a")})
