from decimal import Decimal

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.expected_value import Recommendation, evaluate
from ground_truth.triage.ingest import Intent
from ground_truth.triage.sensitivity import find_flip_point, sweep

ACC = Interval(point=0.92, low=0.905, high=0.935, n=180, method="cluster-BCa")
AUTO_COST = Decimal("0.10")


def intent(cost: str) -> Intent:
    return Intent(
        intent="invoice_total",
        volume_per_month=1000,
        current_cost_per_item=Decimal("2.00"),
        cost_of_error=Decimal(cost),
        client_quote="the client's own words",
        unbounded_error=False,
    )


def test_flip_point_actually_flips_the_recommendation():
    fp = find_flip_point(intent("4.00"), ACC, AUTO_COST, ceiling=Decimal("1000"))
    assert fp.flips_at is not None
    below = evaluate(intent(str(fp.flips_at - Decimal("1.00"))), ACC, AUTO_COST).recommendation
    above = evaluate(intent(str(fp.flips_at + Decimal("1.00"))), ACC, AUTO_COST).recommendation
    assert below != above, "the reported flip point must be a real boundary"


def test_sentence_is_in_the_clients_units():
    fp = find_flip_point(intent("4.00"), ACC, AUTO_COST, ceiling=Decimal("1000"))
    assert "$" in fp.sentence and str(fp.flips_at) in fp.sentence


def test_sentence_quotes_the_client():
    fp = find_flip_point(intent("4.00"), ACC, AUTO_COST, ceiling=Decimal("1000"))
    assert "the client's own words" in fp.sentence


def test_no_flip_within_ceiling_is_reported_as_none():
    fp = find_flip_point(intent("0.01"), ACC, AUTO_COST, ceiling=Decimal("0.02"))
    assert fp.flips_at is None and "does not flip" in fp.sentence


def test_sweep_is_monotone_towards_route_to_human():
    rows = sweep(intent("4.00"), ACC, AUTO_COST, ceiling=Decimal("500"), steps=50)
    ranks = {
        Recommendation.AUTOMATE: 0,
        Recommendation.INSUFFICIENT_EVIDENCE: 1,
        Recommendation.ROUTE_TO_HUMAN: 2,
    }
    values = [ranks[r] for _, r in rows]
    assert values == sorted(values), (
        "raising cost of error can never make automation more attractive"
    )


def test_unbounded_intent_never_flips():
    unbounded = Intent(
        intent="bank",
        volume_per_month=10,
        current_cost_per_item=Decimal("1"),
        cost_of_error=None,
        client_quote="q",
        unbounded_error=True,
    )
    fp = find_flip_point(unbounded, ACC, AUTO_COST, ceiling=Decimal("1000"))
    assert fp.flips_at is None and fp.from_rec is Recommendation.NEVER_AUTOMATE
