"""Cohen's kappa and Krippendorff's alpha for judge/human agreement measurement.

Licence note (brief Task 26, Step 1): the `krippendorff` PyPI package is GPL-3.0-or-later
(confirmed via https://pypi.org/pypi/krippendorff/json -- license expression
"GPL-3.0-or-later", classifier "GNU General Public License v3 (GPLv3)"). `00`'s permissive-
licences-only rule rules it out, so nominal alpha is implemented directly below rather than
wrapping that dependency.
"""

from __future__ import annotations

from collections import Counter
from itertools import permutations

import numpy as np

from ground_truth.stats.bootstrap import Interval, zero_count_upper_bound

CONFIDENCE: float = 0.95
BOOTSTRAP_RESAMPLES: int = 10_000  # docs/analysis-plan.md, "Confidence intervals"


def cohens_kappa(rater_a: list[str], rater_b: list[str]) -> float:
    if len(rater_a) != len(rater_b):
        raise ValueError("rater_a and rater_b must have the same length")
    n = len(rater_a)
    po = sum(a == b for a, b in zip(rater_a, rater_b, strict=True)) / n
    counts_a = Counter(rater_a)
    counts_b = Counter(rater_b)
    categories = set(counts_a) | set(counts_b)
    pe = sum((counts_a[c] / n) * (counts_b[c] / n) for c in categories)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def confusion_matrix(rater_a: list[str], rater_b: list[str]) -> dict[tuple[str, str], int]:
    matrix: dict[tuple[str, str], int] = {}
    for a, b in zip(rater_a, rater_b, strict=True):
        matrix[(a, b)] = matrix.get((a, b), 0) + 1
    return matrix


def _disagreement(ratings: dict[str, dict[str, str]]) -> tuple[float, float]:
    """`(observed, expected)` disagreement -- alpha's two components, `Do` and `De`.

    Split out of `krippendorff_alpha` so `alpha_bootstrap_ci`, which needs `De` on its own for
    the zero-disagreement case, shares one implementation of the formula rather than carrying
    a second copy. Same inputs, same `ValueError`s, and `krippendorff_alpha` is now literally
    `1 - Do/De`.
    """
    units: dict[str, list[str]] = {}
    for rater_ratings in ratings.values():
        for unit, value in rater_ratings.items():
            units.setdefault(unit, []).append(value)

    coincidence: dict[tuple[str, str], float] = {}
    marginal: dict[str, float] = {}
    n = 0.0
    for values in units.values():
        m_u = len(values)
        if m_u < 2:  # noqa: PLR2004 -- a unit needs >=2 raters to contribute a coincidence
            continue
        weight = 1.0 / (m_u - 1)
        for v_i, v_j in permutations(values, 2):
            coincidence[(v_i, v_j)] = coincidence.get((v_i, v_j), 0.0) + weight
            marginal[v_i] = marginal.get(v_i, 0.0) + weight
        n += m_u

    if n == 0:
        raise ValueError("no unit was rated by two or more raters; alpha is undefined")

    do = sum(w for (c, k), w in coincidence.items() if c != k) / n
    categories = list(marginal)
    de_sum = sum(marginal[c] * marginal[k] for c in categories for k in categories if c != k)
    de = de_sum / (n * (n - 1))
    if de == 0.0:
        raise ValueError(
            "expected disagreement is zero (only one value occurs); alpha is undefined"
        )
    return do, de


def krippendorff_alpha(ratings: dict[str, dict[str, str]]) -> float:
    """Nominal-data alpha per Krippendorff, "Computing Krippendorff's Alpha-Reliability"
    (coincidence-matrix method, section C/E). `ratings` maps rater -> {unit_id: value};
    a rater simply omits units it did not rate. A unit rated by fewer than two raters
    contributes nothing -- this is what makes a partial second rater usable at all.
    """
    do, de = _disagreement(ratings)
    return 1.0 - do / de


def _ratings(pairs: list[tuple[str, str]]) -> dict[str, dict[str, str]]:
    """`krippendorff_alpha`'s rater -> {unit_id: value} shape, keyed by position.

    Position, not the original unit id, because a bootstrap resample draws units *with
    replacement*: a unit drawn three times must contribute three coincidences, and reusing
    its own id would silently collapse those back into one.
    """
    return {
        "judge": {str(i): judge for i, (judge, _) in enumerate(pairs)},
        "human": {str(i): human for i, (_, human) in enumerate(pairs)},
    }


def _zero_disagreement_interval(pairs: list[tuple[str, str]], confidence: float) -> Interval:
    """Exact bound for the case a resampling bootstrap cannot speak to.

    With zero observed disagreements every resample yields alpha = 1.0, so a percentile
    bootstrap would publish "alpha = 1.000 [1.000, 1.000]" -- zero uncertainty at exactly the
    point the claim is strongest. That is audit H5, the same failure `_interval` in this
    package already guards against for accuracy, and it must not reappear on alpha.

    For two raters who both rated every unit, `Do` is the per-unit disagreement proportion, so
    0 disagreements out of n carries the exact two-sided Clopper-Pearson upper bound
    `Do_high = 1 - ((1-confidence)/2)**(1/n)` -- `bootstrap.zero_count_upper_bound`, the one
    implementation shared with the accuracy intervals' constant-data branch. `De` is a
    function of the observed marginals and is held at its observed value, which is what makes
    this a bound on alpha rather than a bootstrap; `alpha_low = 1 - Do_high/De`, floored at
    -1.0, alpha's lower limit.
    """
    n = len(pairs)
    _, de = _disagreement(_ratings(pairs))
    do_high = zero_count_upper_bound(n, confidence)
    return Interval(
        point=1.0,
        low=max(-1.0, 1.0 - do_high / de),
        high=1.0,
        n=n,
        method="clopper-pearson-exact-on-disagreement",
    )


def alpha_bootstrap_ci(
    pairs: list[tuple[str, str]],
    *,
    seed: int,
    confidence: float = CONFIDENCE,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
) -> Interval:
    """Percentile bootstrap of *alpha itself*, resampling whole `(judge, human)` units.

    `graders.judge.agreement` used to build its published interval with `cluster_bootstrap_ci`
    over per-unit raw agreement. Alpha is chance-corrected and the raw rate is not, so the two
    diverge hard under class imbalance: on a 60-unit sample where the judge says EQUIVALENT
    every time and the human agrees with half of it, alpha = -0.322 while the raw-rate interval
    is [0.373, 0.627] -- a published "alpha [low, high]" sentence whose interval did not contain
    its own point estimate. CLAUDE.md rules 2 and 3 both require the interval to describe the
    uncertainty of the number it is attached to, and alpha is the number driving the judge
    accept/reject decision.

    `cluster_bootstrap_ci` could not carry this: it is built around a mean of per-cluster
    proportions, and its constant-data branch is a binomial bound that has no meaning on
    alpha's [-1, 1] scale. Percentile rather than BCa because alpha is not a statistic scipy
    can jackknife across an axis; the `method` string says which was used rather than borrowing
    the BCa label the accuracy intervals carry.
    """
    if not pairs:
        raise ValueError("cannot compute an interval from zero units")
    n = len(pairs)
    if all(judge == human for judge, human in pairs):
        return _zero_disagreement_interval(pairs, confidence)

    rng = np.random.default_rng(seed)
    defined: list[float] = []
    for _ in range(n_resamples):
        draw = [pairs[k] for k in rng.integers(0, n, size=n)]
        try:
            defined.append(krippendorff_alpha(_ratings(draw)))
        except ValueError:
            # This resample drew only agreeing units of a single category, so alpha is 0/0.
            # Excluded, not scored: the full-sample 0/0 publishes as undefined and REJECTED
            # (`graders.judge.agreement._undefined_alpha_report`), and scoring the resample
            # 1.0 instead put a spike at perfect agreement that pulled the upper percentile to
            # 1.000 on imbalanced samples (stats code review 2026-09-27, finding 7). The
            # interval is therefore conditional on alpha being defined, and says so.
            continue
    n_undefined = n_resamples - len(defined)

    method = "unit-bootstrap-percentile"
    if n_undefined:
        method += f", {n_undefined} of {n_resamples} undefined resamples excluded"
    if defined:
        tail = (1.0 - confidence) / 2.0 * 100.0
        low, high = (float(v) for v in np.percentile(np.asarray(defined), [tail, 100.0 - tail]))
    else:
        # Every resample was 0/0, so there is no distribution to take percentiles of. NaN
        # bounds, not a crash: `assess` rejects a judge whose interval cannot be estimated.
        low = high = float("nan")
    return Interval(
        point=krippendorff_alpha(_ratings(pairs)),
        low=low,
        high=high,
        n=n,
        method=method,
    )
