import random

import pytest
from scipy.stats import beta

from ground_truth.stats.bootstrap import (
    Interval,
    cluster_bootstrap_ci,
    naive_bootstrap_ci,
    zero_count_upper_bound,
)


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
    # Two-sided 95% (0.025 per tail), matching every other interval this package publishes --
    # the one-sided bound (0.9835) was 95% on a different footing (stats review 2026-09-27,
    # finding 3). Cross-checked: scipy.stats.beta.ppf(0.025, 180, 1) = 0.979715.
    assert ci.low == pytest.approx(0.979715, abs=1e-6), "two-sided Clopper-Pearson at n=180"
    assert ci.high == 1.0


def test_zero_score_still_carries_uncertainty():
    ci = cluster_bootstrap_ci([(f"i{i}", False) for i in range(180)], seed=1, n_resamples=200)
    assert ci.point == 0.0 and ci.low == 0.0 and ci.high == pytest.approx(0.020285, abs=1e-6)


def constant_replicated_score(n_items: int, k: int, replicates: int = 5):
    """Every item scores exactly k/replicates -- a real, non-random constant per-item mean,
    matching the project's n>=5 replicate rule. Deterministic pattern: first k replicates
    correct, rest wrong."""
    return [(f"i{i}", r < k) for i in range(n_items) for r in range(replicates)]


@pytest.mark.parametrize("k", [0, 1, 2, 3, 4, 5])
def test_every_achievable_constant_score_under_five_replicates_has_a_nonzero_bracket(k):
    """audit review: `float(values.std()) == 0.0` missed every constant except the two
    extremes, because floating-point summation over many identical non-0/1 values doesn't
    reliably reproduce an exact 0.0 std. A slot where every item scores exactly k/5 (k in
    1..4) is a real, reachable shape -- `values.min() == values.max()` must catch it."""
    ci = cluster_bootstrap_ci(constant_replicated_score(60, k), seed=1, n_resamples=200)
    assert ci.point == pytest.approx(k / 5)
    assert ci.low <= ci.point <= ci.high
    if k in (0, 5):
        assert ci.method == "clopper-pearson-exact"
    else:
        # not a 0/1 constant, so no binomial bound is computed -- the label must say so,
        # not borrow "clopper-pearson-exact" for a bound that was never computed.
        assert ci.method == "degenerate-zero-variance"
        assert ci.low < ci.high, "the old std==0.0 bug reported this case as zero-width"


@pytest.mark.parametrize("k", [0, 3, 5])
def test_single_cluster_constant_score_still_carries_uncertainty(k):
    """n=1 (a single item) is another highly reachable degenerate shape: the values array
    always has min == max because there's only one value in it."""
    ci = cluster_bootstrap_ci(constant_replicated_score(1, k), seed=1, n_resamples=200)
    assert ci.n == 1
    assert ci.low <= ci.point <= ci.high
    assert ci.low < ci.high, "n=1 must not collapse to a zero-width interval either"


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


@pytest.mark.parametrize("n", [1, 15, 60, 180, 500])
def test_zero_count_upper_bound_matches_exact_beta_quantile(n):
    """The one shared two-sided Clopper-Pearson bound for 0 events in n trials. Both
    `_interval` (accuracy at 0/n and n/n) and `agreement._zero_disagreement_interval` (Do at
    0 disagreements) use it, so a change to the tail convention cannot reach only one of them
    (stats code review 2026-09-27, finding 9). Exact reference: Beta(1, n) upper quantile."""
    assert zero_count_upper_bound(n, 0.95) == pytest.approx(beta.ppf(0.975, 1, n), abs=1e-12)


def test_zero_count_upper_bound_rejects_an_empty_sample():
    with pytest.raises(ValueError):
        zero_count_upper_bound(0, 0.95)
