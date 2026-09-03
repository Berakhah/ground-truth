from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ground_truth._bok_shim import Sensitivity, SensitivityViolation
from ground_truth.policy import assert_slot_may_see
from ground_truth.providers import SlotSpec

MODELS_YAML = Path("models.yaml")


def spec(slot: str, *, trains: bool = False, commercial: bool = True) -> SlotSpec:
    return SlotSpec(
        slot=slot,
        family="FAMILY-X",
        provider="provider-x",
        model_ref="MODEL-REF-X",
        trains_on_data=trains,
        commercial_use=commercial,
        exposes_fingerprint=False,
        list_price_in_per_1m=Decimal("0.10"),
        list_price_out_per_1m=Decimal("0.40"),
        pricing_url="https://example.invalid/pricing",
        retrieved_at=date(2026, 8, 31),
    )


def check(sensitivity: Sensitivity, **kw: bool) -> None:
    assert_slot_may_see("s", sensitivity, {"s": spec("s", **kw)}, MODELS_YAML)


def test_confidential_refused_when_the_slot_trains_on_submitted_input():
    with pytest.raises(SensitivityViolation, match="trains_on_data=True"):
        check(Sensitivity.CLIENT_CONFIDENTIAL, trains=True)


def test_confidential_refused_when_the_slot_is_not_cleared_for_commercial_use():
    with pytest.raises(SensitivityViolation, match="commercial_use=False"):
        check(Sensitivity.CLIENT_CONFIDENTIAL, commercial=False)


def test_confidential_allowed_on_a_non_training_commercial_slot():
    assert check(Sensitivity.CLIENT_CONFIDENTIAL) is None


def test_redacted_is_allowed_on_a_training_slot():
    """The 2026-09-03 decision: training providers stay in the slot list and are fed the
    redacted/synthetic corpus variant rather than being dropped. Gating REDACTED here would
    silently undo that choice."""
    assert check(Sensitivity.REDACTED, trains=True) is None
    assert check(Sensitivity.SYNTHETIC, trains=True) is None
    assert check(Sensitivity.PUBLIC, trains=True) is None


def test_confidential_refused_when_the_slot_is_not_declared_at_all():
    """Fail closed. An undeclared slot has no recorded data policy, so it cannot be cleared."""
    with pytest.raises(SensitivityViolation, match="not declared"):
        assert_slot_may_see("ghost", Sensitivity.CLIENT_CONFIDENTIAL, {}, MODELS_YAML)


def test_refusal_cites_the_manifest_it_read_and_the_date_on_it():
    with pytest.raises(SensitivityViolation) as exc:
        check(Sensitivity.CLIENT_CONFIDENTIAL, trains=True)
    message = str(exc.value)
    assert "models.yaml" in message and "2026-08-31" in message, (
        "a refusal a client's counsel cannot audit is not a control"
    )
    assert "provider-x" in message and "MODEL-REF-X" in message, (
        "the policy is per model x provider endpoint, so the refusal must name both"
    )
