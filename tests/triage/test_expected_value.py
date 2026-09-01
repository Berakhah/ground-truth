from decimal import Decimal

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.expected_value import Recommendation, evaluate
from ground_truth.triage.ingest import Intent


def intent(**over) -> Intent:
    base = dict(
        intent="invoice_total",
        volume_per_month=1000,
        current_cost_per_item=Decimal("2.00"),
        cost_of_error=Decimal("4.00"),
        client_quote="four dollars of rework",
        unbounded_error=False,
    )
    return Intent(**(base | over))


def acc(point, low, high, n=180) -> Interval:
    return Interval(point=point, low=low, high=high, n=n, method="cluster-BCa")


def test_ev_is_an_interval_derived_from_the_accuracy_interval():
    r = evaluate(intent(), acc(0.92, 0.89, 0.95), Decimal("0.10"))
    assert r.ev_low < r.ev_point < r.ev_high


def test_high_accuracy_low_cost_of_error_automates():
    r = evaluate(intent(), acc(0.92, 0.90, 0.94), Decimal("0.10"))
    assert r.recommendation is Recommendation.AUTOMATE


def test_high_accuracy_high_cost_of_error_routes_to_human():
    r = evaluate(intent(cost_of_error=Decimal("40000")), acc(0.97, 0.95, 0.99), Decimal("0.10"))
    assert r.recommendation is Recommendation.ROUTE_TO_HUMAN


def test_unbounded_error_never_automates_regardless_of_ev():
    r = evaluate(
        intent(cost_of_error=None, unbounded_error=True), acc(0.999, 0.998, 1.0), Decimal("0.01")
    )
    assert r.recommendation is Recommendation.NEVER_AUTOMATE


def test_ev_interval_spanning_zero_is_insufficient_evidence():
    r = evaluate(intent(cost_of_error=Decimal("25")), acc(0.90, 0.75, 0.99, n=40), Decimal("0.10"))
    assert r.recommendation is Recommendation.INSUFFICIENT_EVIDENCE
    assert "n=40" in r.rationale


def test_rationale_always_states_n():
    assert "n=180" in evaluate(intent(), acc(0.92, 0.90, 0.94), Decimal("0.10")).rationale


def test_unbounded_rationale_quotes_the_client():
    r = evaluate(
        intent(cost_of_error=None, unbounded_error=True, client_quote="we may never recover it"),
        acc(0.99, 0.98, 1.0),
        Decimal("0.01"),
    )
    assert "we may never recover it" in r.rationale


def test_no_float_in_the_money_path():
    import inspect  # noqa: PLC0415

    from ground_truth.triage import expected_value  # noqa: PLC0415

    assert "float(" not in inspect.getsource(expected_value)
