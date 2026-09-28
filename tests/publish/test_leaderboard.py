# tests/publish/test_leaderboard.py
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ground_truth.matrix.build import LeaderboardRow, distinguishability_statements
from ground_truth.matrix.cost import cost_per_1k_items
from ground_truth.matrix.latency import summarise_latency
from ground_truth.providers import SlotSpec
from ground_truth.publish.leaderboard import (
    assert_methodology_defines_every_term,
    leaderboard_payload,
    required_terms,
)
from ground_truth.stats.bootstrap import Interval

METHODOLOGY = Path(__file__).resolve().parents[2] / "docs" / "methodology.md"
AS_OF = datetime(2026, 10, 15, tzinfo=UTC)


def spec(slot):
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
        retrieved_at=AS_OF.date(),
    )


def row(slot, low, point, high):
    return LeaderboardRow(
        slot=slot,
        accuracy=Interval(point=point, low=low, high=high, n=180, method="cluster-BCa"),
        cost=cost_per_1k_items(spec(slot), 2000),
        latency=summarise_latency([100, 200, 300]),
        per_field={},
    )


def payload():
    rows = [row("slot-a", 0.89, 0.92, 0.95), row("slot-b", 0.90, 0.93, 0.96)]
    return leaderboard_payload(
        rows, distinguishability_statements(rows), [], [], as_of=AS_OF, version="2026.10.15"
    )


def test_every_row_carries_its_n_and_interval():
    for entry in payload()["rows"]:
        assert set(entry["accuracy"]) >= {"point", "low", "high", "n", "method"}
        assert entry["accuracy"]["n"] == 180  # noqa: PLR2004


def test_distinguishability_statements_are_included():
    assert any("not distinguishable" in s for s in payload()["distinguishability"])


def test_cost_carries_the_list_price_caveat():
    for entry in payload()["rows"]:
        assert "list price" in entry["cost"]["caveat"].lower()


def test_latency_has_no_rank_key():
    for entry in payload()["rows"]:
        assert "rank" not in entry["latency"]


def test_payload_is_versioned_and_dated():
    body = payload()
    assert body["version"] == "2026.10.15" and body["as_of"] == AS_OF.isoformat()


def test_payload_links_the_methodology():
    assert payload()["methodology_url"]


def test_methodology_defines_every_published_term():
    assert_methodology_defines_every_term(METHODOLOGY)


def test_required_terms_covers_the_published_vocabulary():
    assert {"accurate", "correct", "field", "item", "replicate", "split"} <= required_terms()


def test_methodology_states_the_population():
    """audit M1: `04` §12 requires the methodology to define every published term — the
    missing definition was the **population**. "No claim without its sample" needs its twin:
    no claim without its population. The corpus is synthetic; every headline number's
    external validity to real pay applications is unmeasured, and the Scope section must
    say so before any number does."""
    text = METHODOLOGY.read_text(encoding="utf-8").lower()
    for phrase in ("synthetic", "not real pay applications", "external validity"):
        assert phrase in text, f"methodology Scope section must state: {phrase}"
