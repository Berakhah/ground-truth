import pytest

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.graders.deterministic.normalised import AMBIGUOUS, grade_normalised, normalise

NAME_RULE = RubricRule(
    grader="normalised",
    normalisation=["casefold", "strip_accents", "strip_legal_suffix"],
    acceptable_variants=["Acme Construction=Acme Constr"],
)
DATE_RULE = RubricRule(grader="normalised", normalisation=["iso_date"])
ID_RULE = RubricRule(
    grader="normalised", normalisation=["strip_punctuation", "strip_leading_zeros", "casefold"]
)


def field(ftype, value):
    return ItemField(field_name="f", field_type=ftype, expected_value=value)


@pytest.mark.parametrize(
    ("steps", "raw", "expected"),
    [
        (["casefold"], "Acme", "acme"),
        (["strip_accents"], "Béton", "Beton"),
        (["strip_legal_suffix"], "Acme Construction Inc.", "Acme Construction"),
        (["strip_punctuation", "strip_leading_zeros"], "APP-000123", "APP123"),
        (["iso_date"], "1 Sep 2026", "2026-09-01"),
        (["iso_date"], "2026-09-01", "2026-09-01"),
        (["iso_date"], "Sep 1, 2026", "2026-09-01"),
    ],
)
def test_normalise_steps(steps, raw, expected):
    assert normalise(raw, steps) == expected


def test_purely_numeric_slash_date_is_ambiguous():
    assert normalise("01/09/2026", ["iso_date"]) == AMBIGUOUS


def test_unknown_step_raises_rather_than_silently_passing_through():
    with pytest.raises(ValueError, match="unknown normalisation step"):
        normalise("x", ["invent_a_step"])


def test_declared_variant_is_accepted():
    assert grade_normalised(
        field(FieldType.PARTY_NAME, "Acme Construction"), "Acme Constr", NAME_RULE
    ).correct


def test_near_variant_is_rejected():
    assert not grade_normalised(
        field(FieldType.PARTY_NAME, "Acme Construction"), "Acme Concrete", NAME_RULE
    ).correct


def test_case_and_accent_folding_matches():
    assert grade_normalised(field(FieldType.PARTY_NAME, "Béton Inc."), "beton", NAME_RULE).correct


def test_ambiguous_date_is_incorrect_with_a_stated_reason():
    v = grade_normalised(field(FieldType.DATE, "2026-09-01"), "01/09/2026", DATE_RULE)
    assert not v.correct and "ambiguous" in v.reason


def test_identifier_leading_zeros_ignored():
    assert grade_normalised(field(FieldType.IDENTIFIER, "APP-000123"), "app123", ID_RULE).correct


def test_missing_observation_is_incorrect():
    assert not grade_normalised(field(FieldType.DATE, "2026-09-01"), None, DATE_RULE).correct


def test_slash_date_with_only_one_valid_interpretation_is_not_ambiguous():
    # day=25 cannot be a month, so only %d/%m/%Y parses -> resolves, does not return AMBIGUOUS.
    assert normalise("25/01/2026", ["iso_date"]) == "2026-01-25"


def test_slash_date_with_day_equal_to_month_is_not_ambiguous():
    # Both interpretations parse but agree on the same date, so it is not "distinct" per the
    # rubric's own wording -- the single agreed date is returned rather than AMBIGUOUS.
    assert normalise("05/05/2026", ["iso_date"]) == "2026-05-05"
