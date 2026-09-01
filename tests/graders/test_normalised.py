from pathlib import Path

import pytest

from ground_truth.golden.rubric import RubricRule, loaded_rubric
from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.graders.deterministic.normalised import AMBIGUOUS, grade_normalised, normalise

REPO = Path(__file__).resolve().parents[2]
RUBRIC = REPO / "docs" / "rubric.md"

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


def test_parse_to_iso_8601_behaves_identically_to_iso_date():
    """docs/rubric.md's DATE rule names this step parse_to_iso_8601, not iso_date."""
    assert normalise("1 Sep 2026", ["parse_to_iso_8601"]) == normalise("1 Sep 2026", ["iso_date"])
    assert normalise("1 Sep 2026", ["parse_to_iso_8601"]) == "2026-09-01"


def test_strip_ordinal_suffix_works_even_declared_after_parse_to_iso_8601():
    """The real docs/rubric.md DATE order is "parse_to_iso_8601; strip_ordinal_suffix; ...":
    parsing is attempted BEFORE the ordinal-stripping step is reached. A pipeline that only
    strips ordinals when its own step fires would raise on "5th Sep 2026" at the first step,
    never reaching the second -- this proves parsing tolerates ordinals regardless of order."""
    assert normalise("5th Sep 2026", ["parse_to_iso_8601", "strip_ordinal_suffix"]) == "2026-09-05"


def test_strip_ordinal_suffix_is_a_noop_without_one():
    assert normalise("2026-09-01", ["strip_ordinal_suffix"]) == "2026-09-01"


def test_ampersand_to_and_normalises_party_name():
    assert normalise("Smith & Sons", ["ampersand_to_and"]) == "Smith and Sons"


def test_expand_two_digit_year_step_is_recognised_not_unknown():
    """It's a declared, deferred step now -- not an unrecognised one."""
    with pytest.raises(ValueError, match="document"):
        normalise("01/02/03", ["expand_two_digit_year_using_document_context"])


def test_expand_two_digit_year_step_is_a_noop_after_a_successful_parse():
    """docs/rubric.md declares this step AFTER parse_to_iso_8601 for DATE. None of the
    parser's accepted formats admit a two-digit year, so by the time this step is
    reached in that order, the year is already unambiguously 4 digits -- nothing left to
    expand. This is the case every current (4-digit-year) item actually exercises."""
    steps = [
        "parse_to_iso_8601",
        "strip_ordinal_suffix",
        "expand_two_digit_year_using_document_context",
    ]
    assert normalise("1 Sep 2026", steps) == "2026-09-01"


def test_real_rubric_date_and_party_name_rules_grade_a_matching_pair_correct():
    """The gap this file's other new tests were written to close: docs/rubric.md's DATE and
    PARTY_NAME rules, loaded for real (not hand-typed in this file), must actually grade a
    correct extraction as correct. Before the fix, both always failed with "unknown
    normalisation step" regardless of what was extracted."""
    rubric = loaded_rubric(RUBRIC)
    date_rule = rubric[FieldType.DATE]
    party_rule = rubric[FieldType.PARTY_NAME]

    date_field = field(FieldType.DATE, "2026-09-01")
    assert grade_normalised(date_field, "1 Sep 2026", date_rule).correct

    party_field = field(FieldType.PARTY_NAME, "Smith & Sons Inc.")
    assert grade_normalised(party_field, "smith and sons", party_rule).correct
