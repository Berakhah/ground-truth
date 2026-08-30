from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.graders.deterministic.numeric_tolerance import (
    grade_numeric_tolerance,
    parse_decimal,
)

RULE = RubricRule(grader="numeric_tolerance", tolerance=Decimal("0.01"))


def money(value: str) -> ItemField:
    return ItemField(
        field_name="contract_sum",
        field_type=FieldType.MONEY,
        expected_value=value,
        tolerance=Decimal("0.01"),
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234.56", Decimal("1234.56")),
        ("$1,234.56", Decimal("1234.56")),
        ("(1234.56)", Decimal("-1234.56")),
        ("-1234.56", Decimal("-1234.56")),
        ("USD 1234.56", Decimal("1234.56")),
        ("12.5%", Decimal("0.125")),
        ("-0.00", Decimal("0.00")),
    ],
)
def test_parse_decimal_handles_real_document_forms(raw, expected):
    assert parse_decimal(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "-", ".", "not a number", "1.2.3.4.5"])
def test_parse_decimal_raises_on_junk(raw):
    with pytest.raises(ValueError):
        parse_decimal(raw)


def test_unparseable_is_incorrect_not_an_exception():
    v = grade_numeric_tolerance(money("100.00"), "not a number", RULE)
    assert not v.correct and "unparseable" in v.reason


def test_exactly_at_tolerance_is_correct():
    assert grade_numeric_tolerance(money("100.00"), "100.01", RULE).correct


def test_one_unit_inside_tolerance_is_correct():
    assert grade_numeric_tolerance(money("100.00"), "100.00", RULE).correct


def test_one_unit_outside_tolerance_is_incorrect():
    assert not grade_numeric_tolerance(money("100.00"), "100.02", RULE).correct


def test_tolerance_is_symmetric():
    assert grade_numeric_tolerance(money("100.00"), "99.99", RULE).correct
    assert not grade_numeric_tolerance(money("100.00"), "99.98", RULE).correct


def test_field_tolerance_overrides_rule_tolerance():
    field = ItemField(
        field_name="pct",
        field_type=FieldType.PERCENT,
        expected_value="0.125",
        tolerance=Decimal("0.001"),
    )
    assert not grade_numeric_tolerance(field, "0.127", RULE).correct


def test_missing_tolerance_is_incorrect_with_a_clear_reason():
    field = ItemField(field_name="x", field_type=FieldType.MONEY, expected_value="1.00")
    v = grade_numeric_tolerance(field, "1.00", RubricRule(grader="numeric_tolerance"))
    assert not v.correct and "no tolerance" in v.reason


def test_no_float_anywhere_in_the_module():
    import inspect  # noqa: PLC0415

    from ground_truth.graders.deterministic import numeric_tolerance  # noqa: PLC0415

    assert "float(" not in inspect.getsource(numeric_tolerance)


@given(
    value=st.decimals(
        min_value=Decimal("-1e6"),
        max_value=Decimal("1e6"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    )
)
def test_a_value_always_matches_itself(value):
    assert grade_numeric_tolerance(money(str(value)), str(value), RULE).correct
