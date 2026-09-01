from __future__ import annotations

from collections import defaultdict

import numpy as np
from pydantic import BaseModel, ConfigDict
from scipy.stats import bootstrap


class Interval(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    point: float
    low: float
    high: float
    n: int
    method: str

    def overlaps(self, other: Interval) -> bool:
        return self.low <= other.high and other.low <= self.high


def _grouped(observations: list[tuple[str, bool]]) -> list[list[bool]]:
    buckets: dict[str, list[bool]] = defaultdict(list)
    for item_id, correct in observations:
        buckets[item_id].append(correct)
    return [buckets[k] for k in sorted(buckets)]


def _interval(  # noqa: PLR0913, PLR0917 -- private helper, each param is a distinct statistic
    values: np.ndarray, confidence: float, n_resamples: int, seed: int, n: int, method: str
) -> Interval:
    point = float(values.mean())
    if float(values.std()) == 0.0:
        # audit H5: a bootstrap cannot resample variance out of a constant, and the old
        # branch returned low == high == point. A slot scoring 180/180 would have published
        # "1.000 [1.000, 1.000] n=180" -- zero uncertainty at exactly the point a leaderboard
        # makes its strongest claim, and Interval.overlaps would then call it distinguishable
        # from everything. The correct one-sided Clopper-Pearson bound at 180/180 is 0.9835.
        alpha = 1.0 - confidence
        low = alpha ** (1 / n) if point == 1.0 else 0.0
        high = 1.0 - alpha ** (1 / n) if point == 0.0 else 1.0
        return Interval(point=point, low=low, high=high, n=n, method="clopper-pearson-exact")
    res = bootstrap(
        (values,),
        np.mean,
        confidence_level=confidence,
        n_resamples=n_resamples,
        method="BCa",
        random_state=np.random.default_rng(seed),
    )
    return Interval(
        point=point,
        low=float(res.confidence_interval.low),
        high=float(res.confidence_interval.high),
        n=n,
        method=method,
    )


def cluster_bootstrap_ci(
    observations: list[tuple[str, bool]],
    *,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int,
) -> Interval:
    if not observations:
        raise ValueError("cannot compute an interval from zero observations")
    clusters = _grouped(observations)
    means = np.array([float(np.mean(c)) for c in clusters], dtype=float)
    return _interval(means, confidence, n_resamples, seed, len(clusters), "cluster-BCa")


def naive_bootstrap_ci(
    observations: list[tuple[str, bool]],
    *,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int,
) -> Interval:
    """Row-level bootstrap. Present ONLY so test_cluster_bootstrap_wider_than_naive can
    demonstrate the understatement. Never call this from analysis code."""
    if not observations:
        raise ValueError("cannot compute an interval from zero observations")
    rows = np.array([float(c) for _, c in observations], dtype=float)
    return _interval(rows, confidence, n_resamples, seed, len(rows), "naive-BCa")
