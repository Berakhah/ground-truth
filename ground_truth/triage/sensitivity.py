from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.expected_value import Recommendation, evaluate
from ground_truth.triage.ingest import Intent

CENT = Decimal("0.01")


def _money(value: Decimal) -> str:
    """Duplicated from `triage.report._money` (comma-grouped, `$`-prefixed) rather than
    imported: `report.py` already imports from this module, so the reverse import would be
    circular. Three lines; not worth a new shared module for."""
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


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
#
# Amended 2026-09-01 (final review, item 6). from_rec used to always be rec(Decimal(0)) --
# the recommendation at zero cost of error, never the intent's actual stated cost. On the
# repo's own docs/triage-intake-template.csv row (real cost $40.00), that produced a sentence
# reading "this becomes insufficient evidence if a cost exceeds $8.27" while the table right next
# to it already showed "insufficient evidence" as the *current* recommendation -- a future-tense
# claim about a boundary already crossed. from_rec is now rec(real cost), matching the row's own
# EVResult.recommendation, and the search runs in whichever direction actually has a boundary:
# ascending from the real cost towards `ceiling` (the common case -- a not-yet-crossed boundary
# ahead), or descending from the real cost towards $0 when the real cost is already past every
# boundary `ceiling` would reveal ascending (the recommendation flips going *down*, so the
# honest sentence is past tense: "already became X once cost passed $Y").
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

    def no_flip(from_rec: Recommendation) -> FlipPoint:
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

    if intent.unbounded_error:
        return no_flip(Recommendation.NEVER_AUTOMATE)

    real_cost = intent.cost_of_error or Decimal(0)
    from_rec = rec(real_cost)
    quote = intent.client_quote

    if real_cost < ceiling and rec(ceiling) != from_rec:
        # Common case: a boundary lies ahead, between the real cost and the ceiling.
        lo, hi = real_cost, ceiling
        while hi - lo > precision:  # invariant: rec(lo) == from_rec != rec(hi)
            mid = ((lo + hi) / 2).quantize(precision)
            lo, hi = (mid, hi) if rec(mid) == from_rec else (lo, mid)
        to_rec = rec(hi)
        sentence = (
            f"This becomes {to_rec.value.replace('_', ' ')} if a wrong extraction costs more "
            f"than {_money(hi)}. The client's stated cost of error is {_money(real_cost)}, in "
            f"their words: {quote!r}."
        )
        return FlipPoint(
            intent=intent.intent, flips_at=hi, from_rec=from_rec, to_rec=to_rec, sentence=sentence
        )

    if real_cost > 0 and rec(Decimal(0)) != from_rec:
        # The real cost is already past every boundary ascending to `ceiling` would reveal,
        # but a boundary still exists below it -- report it looking backward, never forward.
        lo, hi = Decimal(0), real_cost
        while hi - lo > precision:  # invariant: rec(lo) != from_rec == rec(hi)
            mid = ((lo + hi) / 2).quantize(precision)
            lo, hi = (lo, mid) if rec(mid) == from_rec else (mid, hi)
        to_rec = rec(lo)
        sentence = (
            f"This already became {from_rec.value.replace('_', ' ')} once cost of error passed "
            f"{_money(hi)} (below that, it was {to_rec.value.replace('_', ' ')}). The client's "
            f"stated cost of error is {_money(real_cost)}, in their words: {quote!r}."
        )
        return FlipPoint(
            intent=intent.intent, flips_at=hi, from_rec=from_rec, to_rec=to_rec, sentence=sentence
        )

    return no_flip(from_rec)
