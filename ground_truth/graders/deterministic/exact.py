from __future__ import annotations

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import ItemField
from ground_truth.graders.base import Verdict, collapse_whitespace

GRADER_ID = "exact"
GRADER_VERSION = "1"


def grade_exact(field: ItemField, observed: str | None, rule: RubricRule) -> Verdict:
    if observed is None:
        return Verdict(
            correct=False,
            reason="no output for field",
            grader_id=GRADER_ID,
            grader_version=GRADER_VERSION,
        )
    got = collapse_whitespace(observed)
    want = collapse_whitespace(field.expected_value)
    return Verdict(
        correct=got == want,
        reason="exact match" if got == want else f"expected {want!r}, got {got!r}",
        grader_id=GRADER_ID,
        grader_version=GRADER_VERSION,
    )
