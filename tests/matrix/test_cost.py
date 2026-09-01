from datetime import date
from decimal import Decimal

import pytest

from ground_truth.matrix.cost import LIST_PRICE_CAVEAT, cost_per_1k_items
from ground_truth.providers import SlotSpec


def spec(**over) -> SlotSpec:
    base = dict(slot="slot-a", family="fam", provider="prov", model_ref="ref",
                trains_on_data=False, commercial_use=True, exposes_fingerprint=False,
                list_price_in_per_1m=Decimal("0.10"), list_price_out_per_1m=Decimal("0.40"),
                pricing_url="https://example.invalid/pricing", retrieved_at=date(2026, 8, 31))
    return SlotSpec(**(base | over))


def test_cost_is_computed_from_list_price():
    # 1000 items x (2000 in + 500 out) = 2,000,000 in + 500,000 out
    # = 2 * 0.10 + 0.5 * 0.40 = 0.40
    assert cost_per_1k_items(spec(), 2000, 500).value == Decimal("0.4000")


def test_value_is_decimal_not_float():
    assert isinstance(cost_per_1k_items(spec(), 2000, 500).value, Decimal)


def test_caveat_is_always_attached():
    assert cost_per_1k_items(spec(), 2000, 500).caveat == LIST_PRICE_CAVEAT


def test_caveat_names_list_price_and_denies_measured_spend():
    lowered = LIST_PRICE_CAVEAT.lower()
    assert "list price" in lowered and "not measured spend" in lowered


def test_provenance_travels_with_the_number():
    claim = cost_per_1k_items(spec(), 2000, 500)
    assert claim.source_url == "https://example.invalid/pricing"
    assert claim.retrieved_at == date(2026, 8, 31)
    assert claim.method == "DERIVED"


def test_zero_tokens_raises_rather_than_reporting_free():
    with pytest.raises(ValueError):
        cost_per_1k_items(spec(), 0, 0)


def test_no_float_in_the_module():
    import inspect

    from ground_truth.matrix import cost

    assert "float(" not in inspect.getsource(cost)
