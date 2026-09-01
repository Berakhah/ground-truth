from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.expected_value import Recommendation, evaluate
from ground_truth.triage.ingest import Intent

CENT = Decimal("0.01")


class FlipPoint(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    intent: str
    flips_at: Decimal | None
    from_rec: Recommendation
    to_rec: Recommendation | None
    sentence: str


def sweep(
    intent: Intent,
    accuracy: Interval,
    automation_cost_per_item: Decimal,
    *,
    ceiling: Decimal,
    steps: int = 200,
) -> list[tuple[Decimal, Recommendation]]:
    if intent.unbounded_error:
        rec = evaluate(intent, accuracy, automation_cost_per_item).recommendation
        # cost_of_error is None precisely when unbounded_error is True; the reported x-value is
        # never load-bearing here since the recommendation is always NEVER_AUTOMATE regardless
        # (same defaulting as expected_value._ev).
        return [(intent.cost_of_error or Decimal(0), rec)]

    step_size = ceiling / steps
    rows: list[tuple[Decimal, Recommendation]] = []
    for i in range(steps + 1):
        value = (step_size * i).quantize(CENT)
        rec = evaluate(
            intent.model_copy(update={"cost_of_error": value}), accuracy, automation_cost_per_item
        ).recommendation
        rows.append((value, rec))
    return rows


# Amended 2026-08-29 (audit H6). find_flip_point bisects; it does not scan. The original
# returned the first grid point whose recommendation differed, and with the test's own fixture
# (ceiling=1000, steps=200) the grid step is 5.00 while the true AUTOMATE/INSUFFICIENT boundary
# is at 18.10. It reports 20.00, and test_flip_point_actually_flips_the_recommendation then
# probes 19.00 and 21.00 -- both INSUFFICIENT_EVIDENCE, so below != above fails. The reported
# flip point is also wrong by $1.90 in the client's own units, inside the one sentence this plan
# calls the product. Bisection is correct to a stated precision and turns 200 evaluate calls
# into about 17.
def find_flip_point(
    intent: Intent,
    accuracy: Interval,
    automation_cost_per_item: Decimal,
    *,
    ceiling: Decimal,
    precision: Decimal = Decimal("0.01"),
) -> FlipPoint:
    def rec(cost: Decimal) -> Recommendation:
        return evaluate(
            intent.model_copy(update={"cost_of_error": cost}), accuracy, automation_cost_per_item
        ).recommendation

    from_rec = Recommendation.NEVER_AUTOMATE if intent.unbounded_error else rec(Decimal(0))
    if intent.unbounded_error or rec(ceiling) == from_rec:
        return FlipPoint(
            intent=intent.intent,
            flips_at=None,
            from_rec=from_rec,
            to_rec=None,
            sentence=(
                f"This recommendation does not flip anywhere between $0 and "
                f"${ceiling} of cost of error."
            ),
        )
    lo, hi = Decimal(0), ceiling
    while hi - lo > precision:  # invariant: rec(lo) == from_rec != rec(hi)
        mid = ((lo + hi) / 2).quantize(precision)
        lo, hi = (mid, hi) if rec(mid) == from_rec else (lo, mid)
    to_rec = rec(hi)
    sentence = (
        f"This becomes {to_rec.value.replace('_', ' ')} if a wrong extraction costs more than "
        f"${hi}. The client's stated cost of error is ${intent.cost_of_error}, in their "
        f"words: {intent.client_quote!r}."
    )
    return FlipPoint(
        intent=intent.intent, flips_at=hi, from_rec=from_rec, to_rec=to_rec, sentence=sentence
    )
