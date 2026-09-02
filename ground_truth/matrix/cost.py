from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ground_truth.providers import SlotSpec

LIST_PRICE_CAVEAT = (
    "List price for the paid tier, not measured spend. This benchmark runs on free tiers, "
    "where measured cost is zero and therefore meaningless."
)
_PER_MILLION = Decimal("1000000")


@dataclass(frozen=True)
class CostClaim:
    value: Decimal
    unit: str
    method: str
    source_url: str
    retrieved_at: date
    caveat: str


def cost_per_1k_items(spec: SlotSpec, mean_tokens_in: int, mean_tokens_out: int) -> CostClaim:
    if mean_tokens_in <= 0 and mean_tokens_out <= 0:
        raise ValueError("token counts must be positive; a zero cost would be a fabrication")
    value = (
        Decimal(mean_tokens_in) * Decimal(1000) / _PER_MILLION * spec.list_price_in_per_1m
        + Decimal(mean_tokens_out) * Decimal(1000) / _PER_MILLION * spec.list_price_out_per_1m
    ).quantize(Decimal("0.0001"))
    return CostClaim(
        value=value,
        unit="USD per 1,000 items",
        method="DERIVED",
        source_url=spec.pricing_url,
        retrieved_at=spec.retrieved_at,
        caveat=LIST_PRICE_CAVEAT,
    )
