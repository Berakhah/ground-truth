import re
from decimal import Decimal

from ground_truth.golden.generate import ErrorClass, generate, render_document
from ground_truth.golden.schema import FieldType


def test_generation_is_deterministic_for_a_seed():
    a = generate(count=10, seed=7, rubric_version="v1")
    b = generate(count=10, seed=7, rubric_version="v1")
    assert [i.item_id for i in a] == [i.item_id for i in b]


def test_different_seeds_give_different_items():
    a = generate(count=10, seed=7, rubric_version="v1")
    b = generate(count=10, seed=8, rubric_version="v1")
    assert {i.item_id for i in a} != {i.item_id for i in b}


def test_every_field_type_appears_in_the_corpus():
    items = generate(count=60, seed=1, rubric_version="v1")
    seen = {f.field_type for item in items for f in item.fields}
    assert seen == set(FieldType)


def _as_printed(field) -> str:
    """The form the document uses. MONEY is comma-grouped there and bare in the label,
    which is the normalisation the extraction task is supposed to require."""
    if field.field_type is FieldType.MONEY:
        return f"{Decimal(field.expected_value):,.2f}"
    return field.expected_value


def test_labels_are_present_in_the_rendered_document():
    item = generate(count=1, seed=3, rubric_version="v1")[0]
    doc = render_document(item)
    for field in item.fields:
        if field.field_type is FieldType.LINE_ITEM_DESCRIPTION or not field.expected_value:
            continue
        assert _as_printed(field) in doc, f"{field.field_name} label absent from document"


def test_document_does_not_use_the_json_key_names():
    """audit M1. The prompt asks for `contract_sum`; the document says CONTRACT SUM TO DATE.
    If the key appears verbatim this is a string-copy task and the leaderboard measures
    nothing a real invoice would exercise."""
    for item in generate(count=20, seed=4, rubric_version="v1"):
        doc = render_document(item).lower()
        for field in item.fields:
            assert field.field_name.lower() not in doc, (
                f"{field.field_name} appears verbatim in the document"
            )


def test_document_carries_a_distractor_number_that_is_not_a_label():
    """A document in which every number is an answer is not an extraction task."""
    item = generate(count=1, seed=6, rubric_version="v1")[0]
    doc = render_document(item)
    labels = {_as_printed(f) for f in item.fields}
    numbers = set(re.findall(r"\d[\d,]*\.?\d*", doc))
    assert numbers - labels, "no distractor number in the document"


def test_line_item_count_varies_and_matches_the_count_field():
    counts = set()
    for item in generate(count=20, seed=9, rubric_version="v1"):
        lines = [f for f in item.fields if re.fullmatch(r"line_\d+", f.field_name)]
        declared = next(f for f in item.fields if f.field_name == "line_count")
        if declared.expected_value:  # MISSING_FIELD may blank it
            assert len(lines) == int(declared.expected_value)
        counts.add(len(lines))
    assert len(counts) > 1, "a fixed line count makes every document the same shape"
    assert min(counts) >= 3 and max(counts) <= 8  # noqa: PLR2004


def test_every_injected_error_class_actually_corrupts_the_item():
    """audit M2. Three classes were labelled and never injected, and the old test checked
    only that the labels existed. Injection must never draw from the rng, or the clean and
    dirty streams diverge and this comparison stops meaning anything."""
    dirty = generate(count=60, seed=11, rubric_version="v1")
    clean = generate(count=60, seed=11, rubric_version="v1", inject=False)
    seen = set()
    for d, c in zip(dirty, clean, strict=True):
        if d.injected_error is None:
            assert d.fields == c.fields, "an uninjected item differs from its clean twin"
            continue
        assert d.fields != c.fields, f"{d.injected_error} is labelled but injects nothing"
        seen.add(d.injected_error)
    assert seen == {e.value for e in ErrorClass}, "every error class must be exercised"


def test_money_labels_are_clean_decimal_strings():
    for item in generate(count=20, seed=5, rubric_version="v1"):
        for f in item.fields:
            if f.field_type is FieldType.MONEY and f.expected_value:
                Decimal(f.expected_value)  # raises if not a clean decimal string


def test_missing_field_is_labelled_empty_and_absent_from_the_document():
    """The rubric grades an empty label as "absent": a model that invents a value is wrong."""
    items = [
        i
        for i in generate(count=60, seed=11, rubric_version="v1")
        if i.injected_error == ErrorClass.MISSING_FIELD.value
    ]
    assert items, "seed 11 must produce at least one MISSING_FIELD item"
    for item in items:
        blank = [f for f in item.fields if not f.expected_value]
        assert len(blank) == 1, "exactly one field is dropped"


def test_no_aia_form_strings_anywhere():
    banned = ("G702", "G703", "American Institute of Architects", "AIA Document")
    for item in generate(count=20, seed=2, rubric_version="v1"):
        doc = render_document(item)
        assert not any(b in doc for b in banned), "no AIA form artifact may appear in the corpus"


def test_non_affiliation_notice_is_present():
    doc = render_document(generate(count=1, seed=1, rubric_version="v1")[0])
    assert "not affiliated" in doc.lower()
