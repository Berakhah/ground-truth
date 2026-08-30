from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from ground_truth.golden.generate import ErrorClass, generate
from ground_truth.golden.schema import FieldType, Item, ItemField, Source, Split
from ground_truth.graders.deterministic.arithmetic import grade_arithmetic

TOL = Decimal("0.01")

BALANCED = dict(
    line_1="100.00",
    line_2="50.00",
    work_completed="150.00",
    stored_materials="0.00",
    retainage="15.00",
    retainage_rate="10.00",
    total_earned_less_retainage="135.00",
    contract_sum="200.00",
    balance_to_finish="65.00",
)


def build(values: dict[str, str]) -> Item:
    return Item(
        item_id="i1",
        split=Split.PUBLIC,
        rubric_version="v1",
        source=Source.SYNTHETIC,
        content_hash="h",
        fields=[
            ItemField(
                field_name=k,
                field_type=FieldType.PERCENT if k == "retainage_rate" else FieldType.MONEY,
                expected_value=v,
            )
            for k, v in values.items()
        ],
    )


def test_balanced_document_passes():
    assert grade_arithmetic(build(BALANCED), BALANCED, TOL).correct


def test_off_by_one_cent_within_tolerance_passes():
    assert grade_arithmetic(build(BALANCED), BALANCED | {"work_completed": "150.01"}, TOL).correct


def test_off_by_two_cents_fails_and_names_the_rule():
    v = grade_arithmetic(build(BALANCED), BALANCED | {"work_completed": "150.02"}, TOL)
    assert not v.correct and "line sum" in v.reason


def test_retainage_mismatch_is_caught():
    v = grade_arithmetic(build(BALANCED), BALANCED | {"retainage": "20.00"}, TOL)
    assert not v.correct and "retainage" in v.reason


def test_balance_to_finish_mismatch_is_caught():
    v = grade_arithmetic(build(BALANCED), BALANCED | {"balance_to_finish": "60.00"}, TOL)
    assert not v.correct and "balance to finish" in v.reason


def test_multiple_broken_rules_are_all_reported():
    bad = BALANCED | {"retainage": "20.00", "balance_to_finish": "60.00"}
    v = grade_arithmetic(build(BALANCED), bad, TOL)
    assert "retainage" in v.reason and "balance to finish" in v.reason


def test_missing_field_names_the_field():
    bad = {k: v for k, v in BALANCED.items() if k != "work_completed"}
    v = grade_arithmetic(build(BALANCED), bad, TOL)
    assert not v.correct and "work_completed" in v.reason


def test_generator_injected_arithmetic_errors_are_all_caught():
    targets = {
        ErrorClass.RETAINAGE_MISMATCH.value,
        ErrorClass.STORED_MATERIALS_DOUBLE_COUNT.value,
    }
    items = [
        i for i in generate(count=120, seed=17, rubric_version="v1") if i.injected_error in targets
    ]
    assert items, "generator must produce arithmetic error items at this seed"
    for item in items:
        observed = {f.field_name: f.expected_value for f in item.fields}
        assert not grade_arithmetic(item, observed, TOL).correct, f"{item.item_id} slipped through"


@given(
    line_1=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("1e6"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
    line_2=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("1e6"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
    stored=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("1e5"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
    extra=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("1e6"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)
def test_property_any_internally_consistent_document_passes(line_1, line_2, stored, extra):
    """Every document built to satisfy the four rules must pass, for any amounts."""
    work = line_1 + line_2
    retainage = (work * Decimal("10.00") / Decimal(100)).quantize(Decimal("0.01"))
    earned = work + stored - retainage
    contract = work + stored + extra
    values = {
        "line_1": str(line_1),
        "line_2": str(line_2),
        "work_completed": str(work),
        "stored_materials": str(stored),
        "retainage": str(retainage),
        "retainage_rate": "10.00",
        "total_earned_less_retainage": str(earned),
        "contract_sum": str(contract),
        "balance_to_finish": str(contract - earned),
    }
    verdict = grade_arithmetic(build(values), values, TOL)
    assert verdict.correct, verdict.reason


@given(
    delta=st.decimals(
        min_value=Decimal("0.02"),
        max_value=Decimal("1000"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)
def test_property_breaking_the_line_sum_always_fails(delta):
    """Any perturbation beyond tolerance must be caught, at any magnitude."""
    bad = BALANCED | {"work_completed": str(Decimal(BALANCED["work_completed"]) + delta)}
    verdict = grade_arithmetic(build(BALANCED), bad, TOL)
    assert not verdict.correct and "line sum" in verdict.reason
