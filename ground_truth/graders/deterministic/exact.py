from __future__ import annotations

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import ItemField
from ground_truth.graders.base import Verdict, collapse_whitespace
from ground_truth.graders.deterministic.normalised import normalise

GRADER_ID = "exact"
GRADER_VERSION = "1"


def grade_exact(field: ItemField, observed: str | None, rule: RubricRule) -> Verdict:
    """Exact match after whitespace collapsing (unconditional -- this grader's whole point
    is exact matching, not tolerant matching) plus whatever short, explicit normalisation
    steps the rubric declares for this field type (final review item 1: docs/rubric.md
    declares `casefold; strip_whitespace` for ENUM_CATEGORY and `strip_whitespace;
    strip_leading_zeros` for COUNT, and this grader used to silently ignore both). Reuses
    normalised.py's `normalise()` -- same declared-step vocabulary, same dispatch chain --
    rather than a second implementation of casefold/strip_leading_zeros here.
    """
    if observed is None:
        return Verdict(
            correct=False,
            reason="no output for field",
            grader_id=GRADER_ID,
            grader_version=GRADER_VERSION,
        )
    try:
        got = normalise(collapse_whitespace(observed), rule.normalisation)
        want = normalise(collapse_whitespace(field.expected_value), rule.normalisation)
    except ValueError as exc:
        return Verdict(
            correct=False, reason=str(exc), grader_id=GRADER_ID, grader_version=GRADER_VERSION
        )
    return Verdict(
        correct=got == want,
        reason="exact match" if got == want else f"expected {want!r}, got {got!r}",
        grader_id=GRADER_ID,
        grader_version=GRADER_VERSION,
    )
