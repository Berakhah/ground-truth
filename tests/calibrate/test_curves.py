import random

import pytest

from ground_truth.calibrate.curves import (
    ConfidencePoint,
    fit_curve,
    replicate_agreement,
    threshold_for_precision,
)


def test_replicate_agreement_is_the_modal_proportion():
    assert replicate_agreement([True] * 5) == 1.0
    assert replicate_agreement([True, True, True, False, False]) == pytest.approx(0.6)
    assert replicate_agreement([True, False, False, False, False]) == pytest.approx(0.8)


def test_replicate_agreement_rejects_an_empty_sample():
    with pytest.raises(ValueError):
        replicate_agreement([])


def points(n: int, seed: int) -> list[ConfidencePoint]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        score = rng.uniform(0.5, 1.0)
        out.append(ConfidencePoint(f"i{i}", score, rng.random() < score))
    return out


def test_isotonic_curve_is_monotone():
    curve = fit_curve(points(200, 1), points(200, 2), "money", "isotonic")
    ys = [y for _, y in curve.points]
    assert ys == sorted(ys)


def test_platt_curve_fits():
    curve = fit_curve(points(200, 1), points(200, 2), "money", "platt")
    assert curve.method == "platt" and 0.0 <= curve.brier_validate <= 1.0


def test_unknown_method_raises():
    with pytest.raises(ValueError, match="unknown calibration method"):
        fit_curve(points(50, 1), points(50, 2), "money", "magic")


def test_sample_sizes_are_recorded_separately():
    curve = fit_curve(points(120, 1), points(180, 2), "money", "isotonic")
    assert curve.n_fit == 120 and curve.n_validate == 180


def test_divergence_is_small_when_splits_agree():
    assert fit_curve(points(300, 1), points(300, 2), "money", "isotonic").divergence < 0.1


def test_divergence_is_large_when_splits_disagree():
    fit = [ConfidencePoint(f"f{i}", 0.9, True) for i in range(200)]
    validate = [ConfidencePoint(f"v{i}", 0.9, i % 2 == 0) for i in range(200)]
    curve = fit_curve(fit, validate, "money", "isotonic")
    assert curve.divergence > 0.1, (
        "public-fit vs private-validate divergence is the contamination signal"
    )


def test_platt_rejects_a_single_class_fit_split():
    fit = [ConfidencePoint(f"f{i}", 0.9, True) for i in range(50)]
    validate = points(50, 2)
    with pytest.raises(ValueError, match="platt calibration requires"):
        fit_curve(fit, validate, "money", "platt")


def test_fit_curve_rejects_empty_fit_points():
    with pytest.raises(ValueError):
        fit_curve([], points(50, 2), "money", "isotonic")


def test_fit_curve_rejects_empty_validate_points():
    with pytest.raises(ValueError):
        fit_curve(points(50, 1), [], "money", "isotonic")


def test_threshold_for_precision_is_on_the_curve():
    curve = fit_curve(points(300, 1), points(300, 2), "money", "isotonic")
    threshold = threshold_for_precision(curve, 0.9)
    if threshold is not None:
        calibrated = [y for x, y in curve.points if x >= threshold]
        assert calibrated and min(calibrated) >= 0.9 - 1e-6


def test_unreachable_precision_returns_none():
    fit = [ConfidencePoint(f"f{i}", 0.5, i % 2 == 0) for i in range(200)]
    assert threshold_for_precision(fit_curve(fit, list(fit), "money", "isotonic"), 0.99) is None
