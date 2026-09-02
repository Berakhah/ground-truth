"""O'Brien-Fleming alpha spending for the regression watch's pre-registered sequential calendar.

Corrected 2026-08-29 (audit B3). The boundary is *not* `z_{alpha/2} / sqrt(t)` -- that spends
nearly the full alpha budget at the earliest interim looks and inflates the true type-I error
of this 13-look calendar to 0.0721 against the nominal 0.05. The O'Brien-Fleming boundary is
`C / sqrt(t)` where C is solved so the *cumulative* type-I error across all 13 correlated looks
equals alpha -- for this exact pre-registered calendar, C = 2.1023 (calibrated by simulation over
correlated Brownian trajectories; see docs/superpowers/reviews/verify/verify_seq.py and
docs/analysis-plan.md, "Sequential testing calendar"). The constant is valid only for this
13-look, alpha=0.05 pair -- a different calendar requires recalibrating C by the same simulation
and a new analysis-plan version, which is why both `obrien_fleming_boundary` and `spent_alpha`
refuse any other (total_looks, alpha) pair.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

LOOKS_PER_QUARTER = 13

C_OBF_13_LOOKS = 2.1023  # calibrated by test_calibrated_constant_controls_alpha; see the audit


def _check(look: int, total_looks: int) -> None:
    if not 1 <= look <= total_looks:
        raise ValueError(f"look must be between 1 and {total_looks}, got {look}")


def obrien_fleming_boundary(look: int, total_looks: int, *, alpha: float = 0.05) -> float:
    """The O'Brien-Fleming |z| boundary at `look` of `total_looks`: strict early, approaching
    the calibrated critical value at the final look.

    boundary(t) = C_OBF_13_LOOKS / sqrt(t), t = look / total_looks.

    Calibrated for exactly the pre-registered 13-look, alpha=0.05 calendar -- any other
    (total_looks, alpha) pair raises rather than silently applying an uncalibrated constant.
    """
    _check(look, total_looks)
    if (total_looks, alpha) != (LOOKS_PER_QUARTER, 0.05):
        raise ValueError(
            "the boundary constant is calibrated for the pre-registered calendar only; "
            "changing the calendar requires re-calibration and a new analysis-plan version"
        )
    return C_OBF_13_LOOKS / math.sqrt(look / total_looks)


def spent_alpha(look: int, total_looks: int, *, alpha: float = 0.05) -> float:
    """Lan-DeMets O'Brien-Fleming spending function -- a correct closed form, one line.

    alpha(t) = 2 * (1 - Phi(z_{alpha/2} / sqrt(t)))

    Verified cumulative spend at 13 looks: look 4 -> 0.000410, look 7 -> 0.007563,
    look 10 -> 0.025437, look 13 -> 0.050000 exactly. Monotone and totalling alpha with no
    normalisation, which is what makes its test a test rather than a tautology.
    """
    _check(look, total_looks)
    t = look / total_looks
    return 2.0 * (1.0 - float(norm.cdf(float(norm.ppf(1 - alpha / 2)) / math.sqrt(t))))


@dataclass(frozen=True)
class SequentialResult:
    look: int
    total_looks: int
    z: float
    boundary: float
    reject: bool
    statement: str


def evaluate_look(
    z: float, look: int, total_looks: int, *, alpha: float = 0.05
) -> SequentialResult:
    """Compare `z` to the O'Brien-Fleming boundary at this look and compose a statement that
    always names the test, the look, and the boundary -- alerts state their test, and that is
    a publication rule enforced in the string that produces the alert rather than a style guide
    someone has to remember.
    """
    boundary = obrien_fleming_boundary(look, total_looks, alpha=alpha)
    spent = spent_alpha(look, total_looks, alpha=alpha)
    reject = abs(z) > boundary
    if reject:
        statement = (
            f"Change detected at look {look} of {total_looks}: |z| = {abs(z):.3f} exceeds the "
            f"O'Brien-Fleming boundary of {boundary:.3f} (alpha spent to date {spent:.4f})."
        )
    else:
        statement = (
            f"At look {look} of {total_looks}, no change was detected: |z| = {abs(z):.3f} is "
            f"within the O'Brien-Fleming boundary of {boundary:.3f}. This does not mean no "
            "change occurred — see the minimum detectable effect for this sample."
        )
    return SequentialResult(
        look=look,
        total_looks=total_looks,
        z=z,
        boundary=boundary,
        reject=reject,
        statement=statement,
    )
