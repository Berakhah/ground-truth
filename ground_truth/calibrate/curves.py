"""Calibration curves on the replicate-agreement confidence signal.

Fits on the public golden-set split, validates on the private held-out split. The gap
between the two Brier scores ("divergence") is a free contamination detector: if the
public split had somehow leaked into fitting, the curve would keep describing it while
drifting away from the untouched private split, and the gap would grow. This is what
makes brief 02's threshold routing legitimate rather than decorative -- Task 33 owns
the export format for Ledger Sense's consumption.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

_METHODS = ("isotonic", "platt")


@dataclass(frozen=True)
class ConfidencePoint:
    item_id: str
    score: float
    correct: bool


@dataclass(frozen=True)
class CalibrationCurve:
    field_type: str
    method: str
    points: list[tuple[float, float]]
    n_fit: int
    n_validate: int
    brier_fit: float
    brier_validate: float
    divergence: float


def replicate_agreement(verdicts: list[bool]) -> float:
    """Proportion of n>=5 replicates that produced the modal verdict.

    This is the confidence signal being calibrated, not a provider-reported confidence
    figure: it exists for every model regardless of whether the provider exposes one,
    the replicate requirement (`04` B7) already generates it as a byproduct, and
    provider-reported confidence is exactly the uncalibrated number this programme
    exists to distrust. Where a provider does expose its own confidence/logprob, record
    it alongside and publish its own curve for comparison -- but this is the curve
    Ledger Sense consumes.
    """
    if not verdicts:
        raise ValueError("replicate_agreement requires at least one verdict")
    count_true = sum(verdicts)
    count_false = len(verdicts) - count_true
    return max(count_true, count_false) / len(verdicts)


def _brier(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    return float(np.mean((y_prob - y_true) ** 2))


def _predictor(method: str, x: np.ndarray, y: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    """Fit `method` on (x, y) and return a callable mapping raw scores to calibrated ones."""
    if method == "isotonic":
        isotonic = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        isotonic.fit(x, y)
        return lambda values: np.asarray(isotonic.predict(values))
    # method == "platt" -- fit_curve has already rejected anything else.
    logistic = LogisticRegression()
    logistic.fit(x.reshape(-1, 1), y)
    return lambda values: np.asarray(logistic.predict_proba(values.reshape(-1, 1))[:, 1])


def fit_curve(
    fit_points: list[ConfidencePoint],
    validate_points: list[ConfidencePoint],
    field_type: str,
    method: str,
) -> CalibrationCurve:
    if method not in _METHODS:
        raise ValueError(f"unknown calibration method: {method!r}")
    if not fit_points:
        raise ValueError("fit_points must not be empty")
    if not validate_points:
        raise ValueError("validate_points must not be empty")

    x_fit = np.array([p.score for p in fit_points], dtype=float)
    y_fit = np.array([p.correct for p in fit_points], dtype=float)
    x_validate = np.array([p.score for p in validate_points], dtype=float)
    y_validate = np.array([p.correct for p in validate_points], dtype=float)

    predict = _predictor(method, x_fit, y_fit)
    brier_fit = _brier(y_fit, predict(x_fit))
    brier_validate = _brier(y_validate, predict(x_validate))

    domain = np.array(sorted(set(x_fit.tolist())))
    calibrated = predict(domain)
    curve_points = [(float(x), float(y)) for x, y in zip(domain, calibrated, strict=True)]

    return CalibrationCurve(
        field_type=field_type,
        method=method,
        points=curve_points,
        n_fit=len(fit_points),
        n_validate=len(validate_points),
        brier_fit=brier_fit,
        brier_validate=brier_validate,
        divergence=abs(brier_validate - brier_fit),
    )


def threshold_for_precision(curve: CalibrationCurve, target_precision: float) -> float | None:
    """Smallest raw score `x` such that every calibrated value at or above it meets target.

    Walks the curve from the highest raw score down, tracking the running minimum of the
    calibrated values seen so far -- once that minimum drops below target it can only get
    smaller from there (the suffix only grows), so the walk stops the moment the bar is
    missed. Returns None if even the top of the curve never clears it.
    """
    running_min = float("inf")
    threshold: float | None = None
    for x, y in sorted(curve.points, key=lambda p: p[0], reverse=True):
        running_min = min(running_min, y)
        if running_min < target_precision:
            break
        threshold = x
    return threshold
