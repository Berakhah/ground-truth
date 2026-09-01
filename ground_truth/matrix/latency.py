from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FREE_TIER_LATENCY_CAVEAT = (
    "Measured on free tiers. Free-tier latency does not estimate paid-tier latency and is "
    "not comparable across providers with different serving stacks. Reported as a "
    "distribution; models are not ranked on latency."
)


@dataclass(frozen=True)
class LatencyDistribution:
    p50: float
    p95: float
    n: int
    ecdf_x: list[float]
    ecdf_y: list[float]
    caveat: str


def summarise_latency(latencies_ms: list[int]) -> LatencyDistribution:
    if not latencies_ms:
        raise ValueError("cannot summarise an empty latency sample")
    values = np.sort(np.array(latencies_ms, dtype=float))
    n = int(values.size)
    return LatencyDistribution(
        p50=float(np.percentile(values, 50)),
        p95=float(np.percentile(values, 95)),
        n=n,
        ecdf_x=[float(v) for v in values],
        ecdf_y=[(i + 1) / n for i in range(n)],
        caveat=FREE_TIER_LATENCY_CAVEAT,
    )
