"""Per-look boundary for the regression watch's pre-registered 13-look quarterly calendar.

Analysis plan v2 (2026-09-28). Each look is tested on that look's sweep alone against the
quarter's fixed baseline, at the Šidák per-look level `alpha_look = 1 - (1 - alpha)^(1/13)`.
Šidák's inequality holds for two-sided tests on any multivariate normal, so the family-wise
type-I error across the 13 looks is at most `alpha` whatever the correlation the shared baseline
induces between looks -- and that correlation is positive, so the bound is conservative.

Replaced v1, which pooled every look since the start of the quarter and tested the pooled z
against the fixed-constant O'Brien-Fleming boundary `2.1023 / sqrt(t)`. Pooling diluted a change
that starts mid-quarter -- the event a silent provider update produces -- and the boundary was
7.58 at look 1 (stats review 2026-09-27, finding 1; code review 2026-09-27 #2, finding 2). See
docs/analysis-plan.md, "Revision history".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

LOOKS_PER_QUARTER = 13
FAMILY_ALPHA = 0.05

# The published rounding of `per_look_boundary(13)`, stated in docs/analysis-plan.md. The code
# always uses the closed form; a test keeps this constant, the closed form and the plan in step.
PER_LOOK_BOUNDARY_13_LOOKS = 2.8831


def _check(look: int, total_looks: int, alpha: float) -> None:
    # The plan registers exactly this calendar. `per_look_boundary` would happily compute any
    # other, which is what makes the guard necessary: a different calendar is an unregistered
    # change of method, not a parameter (code review 2026-09-27 #3).
    if (total_looks, alpha) != (LOOKS_PER_QUARTER, FAMILY_ALPHA):
        raise ValueError(
            f"only the pre-registered calendar ({LOOKS_PER_QUARTER} looks, family alpha "
            f"{FAMILY_ALPHA}) may be tested; a different one needs a new analysis-plan version"
        )
    if not 1 <= look <= total_looks:
        raise ValueError(f"look must be between 1 and {total_looks}, got {look}")


def per_look_alpha(total_looks: int, *, alpha: float = FAMILY_ALPHA) -> float:
    """The Šidák share of `alpha` for one of `total_looks` tests: 1 - (1 - alpha)^(1/K)."""
    return 1.0 - float((1.0 - alpha) ** (1.0 / total_looks))


def per_look_boundary(total_looks: int, *, alpha: float = FAMILY_ALPHA) -> float:
    """Two-sided |z| critical value at the per-look alpha; the same at every look."""
    return float(norm.ppf(1.0 - per_look_alpha(total_looks, alpha=alpha) / 2.0))


def sidak_adjust(p_value: float, total_looks: int) -> float:
    """A per-look p-value adjusted for the calendar's `total_looks` tests: 1 - (1 - p)^K.

    At or below `alpha` exactly when the per-look p is at or below `per_look_alpha`, so the
    adjusted p is what goes into Benjamini-Hochberg across cells (plan v2, "How the corrections
    stack").
    """
    # -expm1(K * log1p(-p)) is 1 - (1 - p)^K without cancellation, so a tiny p stays tiny
    # instead of rounding to 0 (and a p of 1 stays exactly 1).
    return -math.expm1(total_looks * math.log1p(-p_value)) if p_value < 1.0 else 1.0


@dataclass(frozen=True)
class SequentialResult:
    look: int
    total_looks: int
    z: float
    boundary: float
    alpha_look: float
    p_value: float
    adjusted_p: float
    reject: bool
    # The test, boundary and p-values without a verdict, for callers whose verdict also depends
    # on a correction across cells (`regression.detect`), so the two never disagree in print.
    test: str
    statement: str


def evaluate_look(
    z: float, look: int, total_looks: int, *, alpha: float = FAMILY_ALPHA
) -> SequentialResult:
    """Compare this look's `z` to the per-look boundary and compose a statement that always
    names the test, the look, the boundary and both p-values -- alerts state their test, and
    that is a publication rule enforced in the string that produces the alert rather than a
    style guide someone has to remember.
    """
    _check(look, total_looks, alpha)
    boundary = per_look_boundary(total_looks, alpha=alpha)
    # The survival function, not 1 - cdf: the latter is exactly 0 above |z| ~ 8.3 and would
    # publish "p = 0" for a large drift (code review 2026-09-27 #3).
    p_value = 2.0 * float(norm.sf(abs(z)))
    adjusted_p = sidak_adjust(p_value, total_looks)
    reject = abs(z) > boundary
    test = (
        f"the Šidák per-look boundary of {boundary:.3f} (per-look p = {p_value:.2g}, "
        f"Šidák-adjusted p = {adjusted_p:.2g}; family-wise type-I error of {alpha:g} across the "
        f"{total_looks}-look calendar)"
    )
    if reject:
        statement = (
            f"Change detected at look {look} of {total_looks}: |z| = {abs(z):.3f} exceeds {test}."
        )
    else:
        statement = (
            f"At look {look} of {total_looks}, no change was detected: |z| = {abs(z):.3f} is "
            f"within {test}. This does not mean no change occurred — see the minimum "
            "detectable effect for this sample."
        )
    return SequentialResult(
        look=look,
        total_looks=total_looks,
        z=z,
        boundary=boundary,
        alpha_look=per_look_alpha(total_looks, alpha=alpha),
        p_value=p_value,
        adjusted_p=adjusted_p,
        reject=reject,
        test=test,
        statement=statement,
    )
