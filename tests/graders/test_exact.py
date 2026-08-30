from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.graders.deterministic.exact import grade_exact

RULE = RubricRule(grader="exact")


def field(value: str) -> ItemField:
    return ItemField(field_name="status", field_type=FieldType.ENUM_CATEGORY, expected_value=value)


def test_identical_strings_are_correct():
    assert grade_exact(field("approved"), "approved", RULE).correct


def test_surrounding_whitespace_is_normalised():
    assert grade_exact(field("approved"), "  approved\n", RULE).correct


def test_internal_whitespace_collapses():
    assert grade_exact(field("change order"), "change   order", RULE).correct


def test_case_difference_is_incorrect_for_exact():
    assert not grade_exact(field("approved"), "Approved", RULE).correct


def test_missing_observation_is_incorrect_not_an_error():
    v = grade_exact(field("approved"), None, RULE)
    assert not v.correct and "no output" in v.reason


def test_empty_string_is_incorrect():
    assert not grade_exact(field("approved"), "", RULE).correct


def test_unicode_confusable_is_incorrect():
    assert not grade_exact(field("A-1"), "A‐1", RULE).correct  # U+2010 hyphen


def test_verdict_carries_grader_identity():
    v = grade_exact(field("approved"), "approved", RULE)
    assert v.grader_id == "exact" and v.grader_version == "1"


def test_verdict_is_frozen():
    import pytest  # noqa: PLC0415

    v = grade_exact(field("approved"), "approved", RULE)
    with pytest.raises(Exception):  # noqa: B017
        v.correct = False
