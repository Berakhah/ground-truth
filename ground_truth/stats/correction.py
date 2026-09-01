from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import false_discovery_control


@dataclass(frozen=True)
class Comparison:
    label: str
    p_value: float


@dataclass(frozen=True)
class CorrectedComparison:
    label: str
    p_value: float
    adjusted_p: float
    significant: bool


def benjamini_hochberg(
    comparisons: list[Comparison], *, fdr: float = 0.05
) -> list[CorrectedComparison]:
    if not comparisons:
        return []
    for c in comparisons:
        if not 0.0 <= c.p_value <= 1.0:
            raise ValueError(f"p-value out of range for {c.label!r}: {c.p_value}")
    adjusted = false_discovery_control(
        np.array([c.p_value for c in comparisons], dtype=float), method="bh"
    )
    return [
        CorrectedComparison(
            label=c.label, p_value=c.p_value, adjusted_p=float(adj), significant=bool(adj <= fdr)
        )
        for c, adj in zip(comparisons, adjusted, strict=True)
    ]
