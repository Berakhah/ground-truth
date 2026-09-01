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


def load_slots(path: Path, key: str = "slots") -> dict[str, SlotSpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {name: SlotSpec(slot=name, **body) for name, body in (raw.get(key) or {}).items()}
