from datetime import date
from decimal import Decimal
from pathlib import Path

from ground_truth.providers import load_slots

REPO = Path(__file__).resolve().parents[1]
MODELS_YAML = REPO / "models.yaml"
PROVIDERS_MD = REPO / "docs" / "providers.md"


def test_every_slot_is_documented():
    slots = load_slots(MODELS_YAML)
    doc = PROVIDERS_MD.read_text(encoding="utf-8")
    for spec in slots.values():
        assert spec.provider in doc, f"{spec.provider} is in models.yaml but not docs/providers.md"


def test_every_slot_carries_list_price_and_provenance():
    for spec in load_slots(MODELS_YAML).values():
        assert spec.list_price_in_per_1m > Decimal("0")
        assert spec.list_price_out_per_1m > Decimal("0")
        assert spec.pricing_url.startswith("https://")
        assert isinstance(spec.retrieved_at, date)


def test_no_non_commercial_provider_is_configured():
    offenders = [s.slot for s in load_slots(MODELS_YAML).values() if not s.commercial_use]
    assert offenders == [], f"non-commercial providers cannot serve billable work: {offenders}"


def test_families_are_declared_not_inferred():
    for spec in load_slots(MODELS_YAML).values():
        assert spec.family, "judge same-family rejection depends on a declared family"


def test_slot_count_is_within_design_bounds():
    slots = load_slots(MODELS_YAML)
    assert 1 <= len(slots) <= 6, "design assumes at most six leaderboard slots"  # noqa: PLR2004


def test_judge_slots_load_from_their_own_key():
    judges = load_slots(MODELS_YAML, key="judge_slots")
    assert judges, "at least one judge slot must be configured"
