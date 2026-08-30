import json

import pytest

from ground_truth.golden.schema import FieldType, Item, ItemField, Source, Split
from ground_truth.graders.deterministic.schema import extract_fields, grade_schema


def item() -> Item:
    return Item(
        item_id="i1",
        split=Split.PUBLIC,
        rubric_version="v1",
        source=Source.SYNTHETIC,
        content_hash="h",
        fields=[
            ItemField(
                field_name="contract_sum", field_type=FieldType.MONEY, expected_value="100.00"
            ),
            ItemField(field_name="app_no", field_type=FieldType.IDENTIFIER, expected_value="A1"),
        ],
    )


def test_valid_output_passes():
    assert grade_schema(item(), json.dumps({"contract_sum": "100.00", "app_no": "A1"})).correct


def test_fenced_json_is_tolerated():
    raw = "```json\n" + json.dumps({"contract_sum": "100.00", "app_no": "A1"}) + "\n```"
    assert grade_schema(item(), raw).correct


def test_missing_field_fails_and_names_it():
    v = grade_schema(item(), json.dumps({"contract_sum": "100.00"}))
    assert not v.correct and "app_no" in v.reason


def test_extra_field_fails_and_names_it():
    v = grade_schema(item(), json.dumps({"contract_sum": "1", "app_no": "A1", "surprise": "x"}))
    assert not v.correct and "surprise" in v.reason


def test_non_string_value_fails():
    v = grade_schema(item(), json.dumps({"contract_sum": 100.0, "app_no": "A1"}))
    assert not v.correct and "contract_sum" in v.reason


def test_truncated_json_fails_without_raising():
    v = grade_schema(item(), '{"contract_sum": "100.00", "app_no":')
    assert not v.correct and "invalid json" in v.reason


def test_json_array_is_not_an_object():
    v = grade_schema(item(), '["contract_sum", "app_no"]')
    assert not v.correct and "invalid json" in v.reason


def test_extract_fields_raises_on_prose():
    with pytest.raises(ValueError):
        extract_fields("The contract sum is one hundred dollars.")
