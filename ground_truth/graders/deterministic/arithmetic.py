from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal

from ground_truth.golden.schema import Item
from ground_truth.graders.base import Verdict
from ground_truth.graders.deterministic.numeric_tolerance import parse_decimal

GRADER_ID = "arithmetic"
GRADER_VERSION = "1"

_LINE_FIELD = re.compile(r"line_\d+")

# Fixed fields the four rules read, beyond the item's variable-count line_N rows.
_NEEDED = (
    "work_completed",
    "stored_materials",
    "retainage",
    "retainage_rate",
    "total_earned_less_retainage",
    "contract_sum",
    "balance_to_finish",
)


def _parse_all(observed: dict[str, str], names: list[str]) -> dict[str, Decimal | str]:
    """Parse each named field out of `observed`. A value is either its Decimal or an
    error string ("missing field: x" / "unparseable field: x") -- never raises, so a
    broken field fails only the rule(s) that need it rather than the whole verdict."""
    resolved: dict[str, Decimal | str] = {}
    for name in names:
        raw = observed.get(name)
        if raw is None:
            resolved[name] = f"missing field: {name}"
            continue
        try:
            resolved[name] = parse_decimal(raw)
        except ValueError:
            resolved[name] = f"unparseable field: {name}"
    return resolved


def grade_arithmetic(item: Item, observed: dict[str, str], tolerance: Decimal) -> Verdict:
    """Checks four cross-field formulas a real pay-application must satisfy internally,
    accumulating every broken rule's reason rather than stopping at the first failure.
    `item` is accepted for interface parity with the other deterministic graders but is
    not consulted -- every rule here is defined purely over `observed`.
    """
    del item
    line_names = sorted(k for k in observed if _LINE_FIELD.fullmatch(k))
    values = _parse_all(observed, [*line_names, *_NEEDED])
    reasons: list[str] = []

    def check(
        label: str,
        names: list[str],
        formula: Callable[[dict[str, Decimal]], tuple[Decimal, Decimal]],
    ) -> None:
        """Resolve `names` out of `values` and, if all are present, run `formula` over
        them to get (actual, expected); append `label` to `reasons` if either a needed
        field was missing/unparseable or the two sides differ by more than `tolerance`."""
        errors = [v for name in names if isinstance(v := values[name], str)]
        if errors:
            reasons.append(f"{label}: {'; '.join(errors)}")
            return
        resolved = {name: v for name in names if isinstance(v := values[name], Decimal)}
        actual, expected = formula(resolved)
        if abs(actual - expected) > tolerance:
            reasons.append(f"{label}: {actual} != {expected}")

    # Rule 1: line sum -- sums whatever line_N fields this item declares (3-8 rows,
    # Task 8), never a fixed pair.
    check(
        "line sum",
        [*line_names, "work_completed"],
        lambda r: (sum((r[n] for n in line_names), Decimal("0")), r["work_completed"]),
    )

    # Rule 2: retainage -- retainage_rate is in percentage points (10.00), as the
    # document prints it, so it is divided by 100 rather than treated as a fraction.
    check(
        "retainage",
        ["work_completed", "retainage", "retainage_rate"],
        lambda r: (r["retainage"], r["work_completed"] * r["retainage_rate"] / Decimal(100)),
    )

    # Rule 3: stored materials.
    check(
        "stored materials",
        ["work_completed", "stored_materials", "retainage", "total_earned_less_retainage"],
        lambda r: (
            r["total_earned_less_retainage"],
            r["work_completed"] + r["stored_materials"] - r["retainage"],
        ),
    )

    # Rule 4: balance to finish.
    check(
        "balance to finish",
        ["contract_sum", "total_earned_less_retainage", "balance_to_finish"],
        lambda r: (r["balance_to_finish"], r["contract_sum"] - r["total_earned_less_retainage"]),
    )

    if not reasons:
        return Verdict(
            correct=True,
            reason="all rules hold",
            grader_id=GRADER_ID,
            grader_version=GRADER_VERSION,
        )
    return Verdict(
        correct=False,
        reason="; ".join(reasons),
        grader_id=GRADER_ID,
        grader_version=GRADER_VERSION,
    )
