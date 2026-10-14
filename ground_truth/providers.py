from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SlotSpec(BaseModel):
    slot: str
    family: str = Field(min_length=1)
    provider: str
    model_ref: str
    trains_on_data: bool
    commercial_use: bool
    exposes_fingerprint: bool
    list_price_in_per_1m: Decimal
    list_price_out_per_1m: Decimal
    pricing_url: str
    retrieved_at: date
    judge: str | None = None


def load_slots(path: Path, key: str = "slots") -> dict[str, SlotSpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {name: SlotSpec(slot=name, **body) for name, body in (raw.get(key) or {}).items()}


class SameFamilyJudge(RuntimeError):
    def __init__(self, judge_slot: str, model_slot: str, family: str) -> None:
        super().__init__(
            f"judge {judge_slot!r} and model under test {model_slot!r} share family {family!r}; "
            "self-preference bias makes this judgement indefensible"
        )


def judge_assignments(models_yaml: Path) -> dict[str, str]:
    """Each model slot's judge, validated before any call: it exists and its family differs.
    Declared in models.yaml, never inferred from a model name (spec 8.1)."""
    slots = load_slots(models_yaml)
    judges = load_slots(models_yaml, key="judge_slots")
    assignments: dict[str, str] = {}
    for name, spec in slots.items():
        if spec.judge is None:
            raise ValueError(f"model slot {name!r} names no judge in {models_yaml}")
        if spec.judge not in judges:
            raise ValueError(f"model slot {name!r} names unknown judge {spec.judge!r}")
        if judges[spec.judge].family == spec.family:
            raise SameFamilyJudge(spec.judge, name, spec.family)
        assignments[name] = spec.judge
    return assignments
