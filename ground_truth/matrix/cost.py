from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ground_truth.providers import SlotSpec

LIST_PRICE_CAVEAT = (
    "List price for the paid tier, not measured spend. This benchmark runs on free tiers, "
    "where measured cost is zero and therefore meaningless. Priced at a blended rate (the "
    "unweighted average of published input and output list price per 1M tokens) applied to "
    "the measured token total: the store carries one combined per-call count, not an "
    "input/output split, so this assumes an even split between them rather than measuring "
    "one. For an input-heavy task that assumption skews the figure away from true cost; it "
    "is disclosed here rather than invented as a precise-looking number."
)
_PER_MILLION = Decimal("1000000")
_PLACEHOLDER_MARKER = "placeholder"


@dataclass(frozen=True)
class CostClaim:
    value: Decimal
    unit: str
    method: str
    source_url: str
    retrieved_at: date
    caveat: str


class PlaceholderPricingError(RuntimeError):
    """Raised instead of fabricating a CostClaim from models.yaml's unaudited scaffold
    data. That file's own header says every field in its placeholder rows -- family,
    provider, prices, pricing_url -- is a fake stand-in, not a real provider account
    (Phase 1 Task 2's field audit has not run). Publishing a cost figure built from it
    would look exactly like real list-price data to a reader, which is the fabrication
    CLAUDE.md rule 5 forbids."""


def cost_per_1k_items(spec: SlotSpec, mean_tokens: int) -> CostClaim:
    if _PLACEHOLDER_MARKER in spec.family.lower() or _PLACEHOLDER_MARKER in spec.provider.lower():
        raise PlaceholderPricingError(
            f"slot {spec.slot!r} (family={spec.family!r}, provider={spec.provider!r}) still "
            "carries models.yaml's placeholder scaffold data; replace it with real, dated, "
            "cited pricing before a CostClaim can be published for this slot."
        )
    if mean_tokens <= 0:
        raise ValueError("token count must be positive; a zero cost would be a fabrication")
    blended_price_per_1m = (spec.list_price_in_per_1m + spec.list_price_out_per_1m) / 2
    value = (
        Decimal(mean_tokens) * Decimal(1000) / _PER_MILLION * blended_price_per_1m
    ).quantize(Decimal("0.0001"))
    return CostClaim(
        value=value,
        unit="USD per 1,000 items",
        method="DERIVED",
        source_url=spec.pricing_url,
        retrieved_at=spec.retrieved_at,
        caveat=LIST_PRICE_CAVEAT,
    )
