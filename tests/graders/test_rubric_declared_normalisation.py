"""Final review items 1/2: a structural regression guard, not another hand-typed fixture test.

Both this bug (grade_exact silently ignoring docs/rubric.md's declared `normalisation` for
ENUM_CATEGORY/COUNT) and its sibling in normalised.py (fixed once already at 9b855bc, for
DATE/PARTY_NAME) hid for 21+ tasks because nothing graded a real, differently-formatted-but-
correct pair against the REAL rubric loaded from disk. Hand-typed RubricRule fixtures in
test_exact.py/test_normalised.py can't catch this class of bug -- they only ever declare the
steps their author remembered to declare. This test loads docs/rubric.md itself and checks
every field type it grades with "exact" or "normalised" actually accepts its own declared
normalisation.
"""

from pathlib import Path

from ground_truth.golden.rubric import loaded_rubric
from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.graders.deterministic.exact import grade_exact
from ground_truth.graders.deterministic.normalised import grade_normalised

REPO = Path(__file__).resolve().parents[2]
RUBRIC = REPO / "docs" / "rubric.md"

# (expected_value, differently-formatted-but-correct observed value), one pair per FieldType
# the real rubric currently grades with "exact" or "normalised".
_CASES: dict[FieldType, tuple[str, str]] = {
    FieldType.DATE: ("2026-09-01", "1 Sep 2026"),
    FieldType.IDENTIFIER: ("APP-000123", "app123"),
    FieldType.PARTY_NAME: ("Smith & Sons Inc.", "smith and sons"),
    FieldType.ENUM_CATEGORY: ("Concrete", "concrete"),
    FieldType.COUNT: ("5", "05"),
}


def test_every_declared_exact_or_normalised_rule_grades_its_own_variant_correct():
    rubric = loaded_rubric(RUBRIC)
    exercised: set[FieldType] = set()
    for field_type in FieldType:
        rule = rubric[field_type]
        if rule.grader not in ("exact", "normalised"):
            continue
        assert field_type in _CASES, (
            f"{field_type} is graded {rule.grader!r} by docs/rubric.md but has no "
            "formatted-variant case in this test -- add one before it can ship ungraded"
        )
        expected, observed = _CASES[field_type]
        field = ItemField(field_name="f", field_type=field_type, expected_value=expected)
        grade_fn = grade_exact if rule.grader == "exact" else grade_normalised
        verdict = grade_fn(field, observed, rule)
        assert verdict.correct, (
            f"{field_type}: {rule.grader} grader rejected a rubric-correct, differently "
            f"formatted pair ({expected!r} vs {observed!r}): {verdict.reason}"
        )
        exercised.add(field_type)
    # Guards against this test silently covering nothing if docs/rubric.md's grader
    # assignments change shape without this file being updated to match.
    assert exercised == {
        FieldType.DATE,
        FieldType.IDENTIFIER,
        FieldType.PARTY_NAME,
        FieldType.ENUM_CATEGORY,
        FieldType.COUNT,
    }
