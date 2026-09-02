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


def disagreement(ratings: dict[str, dict[str, str]]) -> tuple[float, float]:
    """`(observed, expected)` disagreement -- alpha's two components, `Do` and `De`.

    Split out of `krippendorff_alpha` so the two callers that need `De` on its own share one
    implementation of the formula rather than each carrying a copy. (`graders.judge.agreement`
    needs it for the zero-disagreement case, where a resampling bootstrap of alpha is
    degenerate and an exact bound has to be computed instead.) Same inputs, same
    `ValueError`s, and `krippendorff_alpha` is now literally `1 - Do/De`.
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
    do, de = disagreement(ratings)
    return 1.0 - do / de
