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


def zero_count_upper_bound(n: int, confidence: float) -> float:
    """Two-sided exact Clopper-Pearson upper bound on p when 0 events occur in n trials.

    P(X=0 | p) = (1-p)**n = (1-confidence)/2 gives p_high = 1 - ((1-confidence)/2)**(1/n), the
    Beta(1, n) upper quantile. Two-sided (half the miss rate per tail) so it sits on the same
    footing as every BCa/percentile interval beside it (stats review 2026-09-27, finding 3).
    The single home of this formula: accuracy at 0/n and n/n here, and observed disagreement at
    0/n in `agreement._zero_disagreement_interval`, both call it, so the tail convention cannot
    change in one and not the other (stats code review 2026-09-27, finding 9).
    """
    if n < 1:
        raise ValueError("a Clopper-Pearson bound needs at least one trial")
    return 1.0 - float(((1.0 - confidence) / 2.0) ** (1.0 / n))


def _interval(  # noqa: PLR0913, PLR0917 -- private helper, each param is a distinct statistic
    values: np.ndarray, confidence: float, n_resamples: int, seed: int, n: int, method: str
) -> Interval:
    point = float(values.mean())
    if values.min() == values.max():
        # audit H5: a bootstrap cannot resample variance out of a constant, and the old
        # branch returned low == high == point. A slot scoring 180/180 would have published
        # "1.000 [1.000, 1.000] n=180" -- zero uncertainty at exactly the point a leaderboard
        # makes its strongest claim, and Interval.overlaps would then call it distinguishable
        # from everything.
        #
        # This guard used to read `float(values.std()) == 0.0`, which is exact-equality on a
        # *derived* float: summing 60 identical 0.8 values doesn't reliably reproduce a std of
        # exactly 0.0, so a constant score like 4/5 defeated the check and let a live
        # zero-width interval through -- the exact bug this branch exists to prevent, just
        # missed for every constant except the two extremes. `values.min() == values.max()`
        # reads the data directly (no floating-point accumulation) and is exact for every
        # constant array.
        # Two-sided (see `zero_count_upper_bound`). It was one-sided (0.9835 at 180/180
        # against 0.9797 two-sided) until stats review 2026-09-27, finding 3.
        if point == 1.0:
            # n successes is 0 failures: the failure rate's upper bound, mirrored.
            return Interval(
                point=point,
                low=1.0 - zero_count_upper_bound(n, confidence),
                high=1.0,
                n=n,
                method="clopper-pearson-exact",
            )
        if point == 0.0:
            return Interval(
                point=point,
                low=0.0,
                high=zero_count_upper_bound(n, confidence),
                n=n,
                method="clopper-pearson-exact",
            )
        # Constant but not 0 or 1 -- e.g. every one of 60 items independently scoring exactly
        # 4/5. Clopper-Pearson is a binomial bound for x successes out of n trials; it isn't
        # defined for a non-0/1 constant, so it is not computed here. [0, 1] is the honest,
        # maximally-conservative bracket for "zero observed variance, unknown true variance" --
        # labelled as what it actually is, not borrowed as "clopper-pearson-exact" for a bound
        # that was never computed.
        return Interval(point=point, low=0.0, high=1.0, n=n, method="degenerate-zero-variance")
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
