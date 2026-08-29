from decimal import Decimal

import pytest

from ground_truth.golden.schema import FieldType, Item, ItemField, Source, Split

EXPECTED_FIELD_TYPES = {
    "MONEY",
    "PERCENT",
    "DATE",
    "IDENTIFIER",
    "PARTY_NAME",
    "ENUM_CATEGORY",
    "COUNT",
    "LINE_ITEM_DESCRIPTION",
}


def test_field_type_is_closed():
    assert {m.name for m in FieldType} == EXPECTED_FIELD_TYPES, (
        "The item schema is closed. Adding a field type is a scope decision, not a code change."
    )


def test_item_rejects_unknown_split():
    with pytest.raises(Exception):  # noqa: B017
        Item(
            item_id="i1",
            split="holdout",
            rubric_version="v1",
            source=Source.SYNTHETIC,
            content_hash="h",
            fields=[],
        )


def test_money_field_carries_decimal_tolerance():
    f = ItemField(
        field_name="contract_sum",
        field_type=FieldType.MONEY,
        expected_value="1000.00",
        expected_normalised=None,
        tolerance=Decimal("0.01"),
    )
    assert isinstance(f.tolerance, Decimal)


def test_tolerance_is_never_float():
    with pytest.raises(Exception):  # noqa: B017
        ItemField(
            field_name="x",
            field_type=FieldType.MONEY,
            expected_value="1",
            expected_normalised=None,
            tolerance=0.01,
        )


def test_injected_error_defaults_to_none():
    item = Item(
        item_id="i1",
        split=Split.PUBLIC,
        rubric_version="v1",
        source=Source.SYNTHETIC,
        content_hash="h",
        fields=[],
    )
    assert item.injected_error is None


def test_items_are_frozen():
    item = Item(
        item_id="i1",
        split=Split.PUBLIC,
        rubric_version="v1",
        source=Source.SYNTHETIC,
        content_hash="h",
        fields=[],
    )
    with pytest.raises(Exception):  # noqa: B017
        item.item_id = "i2"
