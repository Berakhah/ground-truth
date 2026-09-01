import random

import pytest

from ground_truth.stats.bootstrap import Interval, cluster_bootstrap_ci, naive_bootstrap_ci


def replicated(n_items: int, replicates: int, p: float, seed: int):
    rng = random.Random(seed)
    obs = []
    for i in range(n_items):
        easy = rng.random() < p  # the item is easy or hard
        for _ in range(replicates):
            obs.append((f"i{i}", easy if rng.random() < 0.9 else not easy))  # noqa: PLR2004
    return obs


def test_interval_brackets_the_point_estimate():
    ci = cluster_bootstrap_ci(replicated(60, 5, 0.9, seed=1), seed=1, n_resamples=500)
    assert ci.low <= ci.point <= ci.high


def test_n_is_the_item_count_not_the_row_count():
    ci = cluster_bootstrap_ci(replicated(60, 5, 0.9, seed=1), seed=1, n_resamples=500)
    assert ci.n == 60, (  # noqa: PLR2004
        "the sampling unit is the item; reporting 300 would overstate the sample"
    )


def test_cluster_bootstrap_wider_than_naive():
    obs = replicated(60, 5, 0.9, seed=2)
    clustered = cluster_bootstrap_ci(obs, seed=2, n_resamples=2000)
    naive = naive_bootstrap_ci(obs, seed=2, n_resamples=2000)
    assert (clustered.high - clustered.low) > (naive.high - naive.low), (
        "ignoring within-item correlation understates every interval by roughly sqrt(replicates)"
    )


def test_overlapping_intervals_are_detected():
    a = Interval(point=0.90, low=0.87, high=0.93, n=180, method="cluster-BCa")
    b = Interval(point=0.92, low=0.89, high=0.95, n=180, method="cluster-BCa")
    c = Interval(point=0.99, low=0.98, high=1.00, n=180, method="cluster-BCa")
    assert a.overlaps(b) and b.overlaps(a)
    assert not a.overlaps(c)


def test_empty_input_raises_rather_than_returning_a_number():
    with pytest.raises(ValueError):
        cluster_bootstrap_ci([], seed=1)


def test_perfect_score_still_carries_uncertainty():
    """audit H5: a zero-width interval at 180/180 is the loudest possible false claim."""
    ci = cluster_bootstrap_ci([(f"i{i}", True) for i in range(180)], seed=1, n_resamples=200)
    assert ci.point == 1.0
    assert ci.method == "clopper-pearson-exact"
    assert ci.low == pytest.approx(0.9835, abs=1e-3), "one-sided Clopper-Pearson at n=180"
    assert ci.high == 1.0


def test_zero_score_still_carries_uncertainty():
    ci = cluster_bootstrap_ci([(f"i{i}", False) for i in range(180)], seed=1, n_resamples=200)
    assert ci.point == 0.0 and ci.low == 0.0 and ci.high == pytest.approx(0.0165, abs=1e-3)


@pytest.mark.slow
def test_bootstrap_ci_covers_known_parameter():
    p, covered, trials = 0.9, 0, 1000
    for t in range(trials):
        rng = random.Random(1000 + t)
        obs = [(f"i{i}", rng.random() < p) for i in range(180)]
        ci = cluster_bootstrap_ci(obs, seed=t, n_resamples=400)
        if ci.low <= p <= ci.high:
            covered += 1
    rate = covered / trials
    assert 0.93 <= rate <= 0.97, f"nominal 95% interval covered {rate:.3f} of the time"  # noqa: PLR2004
