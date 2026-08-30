from __future__ import annotations

import re
from decimal import Decimal, DecimalException, localcontext

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import ItemField
from ground_truth.graders.base import Verdict

GRADER_ID = "numeric_tolerance"
GRADER_VERSION = "1"

_STRIP = re.compile(r"[^\d,.\-()%]")
_VALID = re.compile(r"^-?\d+(\.\d+)?$")


def parse_decimal(raw: str) -> Decimal:
    text = _STRIP.sub("", raw.strip())
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    percent = text.endswith("%")
    text = text.rstrip("%")
    if "," in text and "." in text:
        text = (
            text.replace(",", "")
            if text.rindex(".") > text.rindex(",")
            else text.replace(".", "").replace(",", ".")
        )
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = f"{head}.{tail}" if len(tail) in (1, 2) else text.replace(",", "")
    if not _VALID.match(text):
        raise ValueError(f"unparseable numeric value: {raw!r}")
    try:
        with localcontext() as ctx:
            ctx.prec = 28
            value = Decimal(text)
    except DecimalException as exc:
        raise ValueError(f"unparseable numeric value: {raw!r}") from exc
    if percent:
        value = value / Decimal(100)
    if negative:
        value = -value
    return value + Decimal(0)  # normalises -0 to 0


def grade_numeric_tolerance(field: ItemField, observed: str | None, rule: RubricRule) -> Verdict:
    def verdict(correct: bool, reason: str) -> Verdict:
        return Verdict(
            correct=correct, reason=reason, grader_id=GRADER_ID, grader_version=GRADER_VERSION
        )

    if observed is None:
        return verdict(False, "no output for field")
    tolerance = field.tolerance if field.tolerance is not None else rule.tolerance
    if tolerance is None:
        return verdict(False, "no tolerance declared in rubric or field")
    try:
        got = parse_decimal(observed)
        want = parse_decimal(field.expected_value)
    except ValueError as exc:
        return verdict(False, str(exc))
    delta = abs(got - want)
    return verdict(
        delta <= tolerance,
        f"|{got} - {want}| = {delta} {'<=' if delta <= tolerance else '>'} {tolerance}",
    )
