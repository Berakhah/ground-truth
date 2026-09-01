# tests/matrix/test_latency.py
import dataclasses

import pytest

from ground_truth.matrix.latency import (
    FREE_TIER_LATENCY_CAVEAT,
    LatencyDistribution,
    summarise_latency,
)


def test_percentiles_are_computed():
    dist = summarise_latency(list(range(1, 101)))
    assert dist.p50 == pytest.approx(50.5, abs=1.0)
    assert dist.p95 == pytest.approx(95.0, abs=1.0)


def test_n_is_reported():
    assert summarise_latency([1, 2, 3]).n == 3


def test_ecdf_is_monotone_and_complete():
    dist = summarise_latency([5, 1, 3, 2, 4])
    assert dist.ecdf_x == sorted(dist.ecdf_x)
    assert dist.ecdf_y[-1] == pytest.approx(1.0)
    assert len(dist.ecdf_x) == len(dist.ecdf_y) == 5


def test_caveat_is_attached():
    assert summarise_latency([1, 2, 3]).caveat == FREE_TIER_LATENCY_CAVEAT


def test_caveat_denies_paid_tier_estimation():
    lowered = FREE_TIER_LATENCY_CAVEAT.lower()
    assert "free tier" in lowered and "paid" in lowered and "not" in lowered


def test_latency_is_not_ranked():
    names = {f.name for f in dataclasses.fields(LatencyDistribution)}
    for banned in ("rank", "position", "place", "fastest"):
        assert banned not in names, "00 B4: latency is a distribution, never a ranking"


def test_empty_input_raises():
    with pytest.raises(ValueError):
        summarise_latency([])
