from datetime import date
from decimal import Decimal

import pytest

from ground_truth.matrix.cost import LIST_PRICE_CAVEAT, PlaceholderPricingError, cost_per_1k_items
from ground_truth.providers import SlotSpec


def spec(**over) -> SlotSpec:
    base = dict(
        slot="slot-a",
        family="fam",
        provider="prov",
        model_ref="ref",
        trains_on_data=False,
        commercial_use=True,
        exposes_fingerprint=False,
        list_price_in_per_1m=Decimal("0.10"),
        list_price_out_per_1m=Decimal("0.40"),
        pricing_url="https://example.invalid/pricing",
        retrieved_at=date(2026, 8, 31),
    )
    return SlotSpec(**(base | over))


def test_cost_is_computed_from_blended_list_price():
    # blended rate = (0.10 + 0.40) / 2 = 0.25 per 1M tokens
    # 1000 items x 2000 tokens = 2,000,000 tokens = 2 * 0.25 = 0.50
    assert cost_per_1k_items(spec(), 2000).value == Decimal("0.5000")


def test_value_is_decimal_not_float():
    assert isinstance(cost_per_1k_items(spec(), 2000).value, Decimal)


def test_caveat_is_always_attached():
    assert cost_per_1k_items(spec(), 2000).caveat == LIST_PRICE_CAVEAT


def test_caveat_names_list_price_and_denies_measured_spend():
    lowered = LIST_PRICE_CAVEAT.lower()
    assert "list price" in lowered and "not measured spend" in lowered


def test_caveat_names_the_blended_methodology():
    lowered = LIST_PRICE_CAVEAT.lower()
    assert "blended" in lowered


def test_provenance_travels_with_the_number():
    claim = cost_per_1k_items(spec(), 2000)
    assert claim.source_url == "https://example.invalid/pricing"
    assert claim.retrieved_at == date(2026, 8, 31)
    assert claim.method == "DERIVED"


def test_zero_tokens_raises_rather_than_reporting_free():
    with pytest.raises(ValueError):
        cost_per_1k_items(spec(), 0)


def test_negative_tokens_raises():
    with pytest.raises(ValueError):
        cost_per_1k_items(spec(), -5)


def test_placeholder_family_refuses_to_price():
    """models.yaml's scaffold rows are literally named PLACEHOLDER-FAMILY-A -- pricing them
    would silently publish a fabricated-looking cost from data the file's own header says
    is fake (see PlaceholderPricingError's docstring)."""
    with pytest.raises(PlaceholderPricingError):
        cost_per_1k_items(spec(family="PLACEHOLDER-FAMILY-A"), 2000)


def test_placeholder_provider_refuses_to_price():
    with pytest.raises(PlaceholderPricingError):
        cost_per_1k_items(spec(provider="placeholder-provider-a"), 2000)


def test_no_float_in_the_module():
    import inspect  # noqa: PLC0415

    from ground_truth.matrix import cost  # noqa: PLC0415

    assert "float(" not in inspect.getsource(cost)
