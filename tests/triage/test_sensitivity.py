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


def test_flip_point_from_rec_matches_the_rows_actual_recommendation():
    """Final review item 6: from_rec must equal the real, current recommendation (evaluate()
    at the client's own stated cost), never a fixed $0 baseline -- otherwise the flip-point
    sentence and the summary table can name two different recommendations for the same row."""
    for cost in ("0.01", "4.00", "18.10", "27.34", "100.00", "900.00"):
        i = intent(cost)
        fp = find_flip_point(i, ACC, AUTO_COST, ceiling=Decimal("1000"))
        actual = evaluate(i, ACC, AUTO_COST).recommendation
        assert fp.from_rec == actual, f"cost={cost}: sentence's from_rec must match the table"


def test_flip_point_looks_backward_when_real_cost_is_already_past_every_boundary():
    """Mirrors the final review's own repro on docs/triage-intake-template.csv: a real cost
    already past every boundary ascending to `ceiling` would reveal (here $900, past this
    fixture's INSUFFICIENT_EVIDENCE -> ROUTE_TO_HUMAN crossing at $27.34) must report a
    past-tense flip ("already became"), never a forward "becomes X if cost exceeds $Y" for a
    Y already crossed -- that phrasing is what the final review flagged as self-contradictory."""
    fp = find_flip_point(intent("900.00"), ACC, AUTO_COST, ceiling=Decimal("1000"))
    assert fp.from_rec is Recommendation.ROUTE_TO_HUMAN
    assert fp.flips_at is not None
    assert "already became" in fp.sentence
    assert "becomes" not in fp.sentence, "never both a past and a forward tense in one sentence"
    below = evaluate(intent(str(fp.flips_at - Decimal("1.00"))), ACC, AUTO_COST).recommendation
    above = evaluate(intent(str(fp.flips_at + Decimal("1.00"))), ACC, AUTO_COST).recommendation
    assert below == fp.to_rec and above == fp.from_rec, "the reported boundary must be real"


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
