from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.ingest import Intent


class Recommendation(StrEnum):
    AUTOMATE = "automate"
    ROUTE_TO_HUMAN = "route_to_human"
    NEVER_AUTOMATE = "never_automate"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EVResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    intent: str
    ev_low: Decimal
    ev_point: Decimal
    ev_high: Decimal
    recommendation: Recommendation
    n: int
    rationale: str


def _ev(intent: Intent, accuracy: Decimal, automation_cost_per_item: Decimal) -> Decimal:
    saving = intent.current_cost_per_item - automation_cost_per_item
    # cost_of_error is None only when unbounded_error is True (enforced by triage.ingest's
    # loader, not by Intent itself); the unbounded_error branch in evaluate() short-circuits
    # to NEVER_AUTOMATE before this value is used, so the 0 default here is never load-bearing.
    cost_of_error = intent.cost_of_error or Decimal(0)
    per_item = accuracy * saving - (Decimal(1) - accuracy) * cost_of_error
    return (Decimal(intent.volume_per_month) * per_item).quantize(Decimal("0.01"))


def evaluate(intent: Intent, accuracy: Interval, automation_cost_per_item: Decimal) -> EVResult:
    ev_low = _ev(intent, Decimal(str(accuracy.low)), automation_cost_per_item)
    ev_point = _ev(intent, Decimal(str(accuracy.point)), automation_cost_per_item)
    ev_high = _ev(intent, Decimal(str(accuracy.high)), automation_cost_per_item)

    if intent.unbounded_error:
        recommendation = Recommendation.NEVER_AUTOMATE
        rationale = (
            f"Cost of error is unbounded in the client's own words: {intent.client_quote!r}. "
            f"No accuracy justifies automation when the downside has no ceiling (n={accuracy.n})."
        )
    elif ev_low > 0:
        recommendation = Recommendation.AUTOMATE
        rationale = (
            f"Expected value is positive across the whole accuracy interval "
            f"[{accuracy.low:.3f}, {accuracy.high:.3f}] at n={accuracy.n}."
        )
    elif ev_high < 0:
        recommendation = Recommendation.ROUTE_TO_HUMAN
        rationale = (
            f"Expected value is negative across the whole accuracy interval "
            f"[{accuracy.low:.3f}, {accuracy.high:.3f}] at n={accuracy.n}."
        )
    else:
        recommendation = Recommendation.INSUFFICIENT_EVIDENCE
        rationale = (
            f"Expected value spans zero: [{ev_low}, {ev_high}] per month at n={accuracy.n}. "
            f"This does not yet support a decision. A larger sample would narrow it."
        )
    return EVResult(
        intent=intent.intent,
        ev_low=ev_low,
        ev_point=ev_point,
        ev_high=ev_high,
        recommendation=recommendation,
        n=accuracy.n,
        rationale=rationale,
    )
