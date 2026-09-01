from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import BaseModel, ConfigDict

COLUMNS: tuple[str, ...] = (
    "intent",
    "volume_per_month",
    "current_cost_per_item",
    "cost_of_error",
    "client_quote",
)
UNBOUNDED = {"unbounded", "unbounded_error", "infinite"}


class Intent(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    intent: str
    volume_per_month: int
    current_cost_per_item: Decimal
    cost_of_error: Decimal | None
    client_quote: str
    unbounded_error: bool = False


def load_intents(path: Path) -> list[Intent]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"expected columns {COLUMNS}, got {reader.fieldnames}")
        intents: list[Intent] = []
        for line, row in enumerate(reader, start=2):
            quote = (row["client_quote"] or "").strip()
            if not quote:
                raise ValueError(
                    f"line {line}: client_quote is required — cost_of_error must be the "
                    "client's number in the client's words, not our estimate"
                )
            raw_cost = (row["cost_of_error"] or "").strip()
            if not raw_cost:
                raise ValueError(f"line {line}: cost_of_error is required")
            unbounded = raw_cost.lower() in UNBOUNDED
            try:
                intents.append(
                    Intent(
                        intent=row["intent"].strip(),
                        volume_per_month=int(row["volume_per_month"]),
                        current_cost_per_item=Decimal(row["current_cost_per_item"]),
                        cost_of_error=None if unbounded else Decimal(raw_cost),
                        client_quote=quote,
                        unbounded_error=unbounded,
                    )
                )
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"line {line}: {exc}") from exc
    return intents
