"""Judge-versus-human agreement, chained to the pre-registered rejection threshold.

No gateway imports, same constraint as `graders.judge.aggregate` (Task 25). `assess` is a pure
function; `record_decision` is this module's one writer, kept as a separate call so `assess`
stays usable with no store at all. `docs/analysis-plan.md`'s "Judge rejection threshold"
section freezes the number below; do not change it without also bumping that document's
`plan_version` (`test_threshold_matches_the_pre_registered_plan` enforces the pairing so the
threshold cannot be nudged after seeing the agreement data).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import duckdb
import numpy as np

from ground_truth.graders.judge.aggregate import (
    LengthEffect,
    OrderEffect,
    Sample,
    length_effect,
    order_effect,
)
from ground_truth.stats.agreement import confusion_matrix, disagreement, krippendorff_alpha
from ground_truth.stats.bootstrap import Interval

REJECTION_THRESHOLD: float = 0.667
BOOTSTRAP_RESAMPLES: int = 10_000  # docs/analysis-plan.md, "Confidence intervals"
CONFIDENCE: float = 0.95


class JudgeStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class AgreementReport:
    field_type: str
    alpha: float
    alpha_ci: Interval
    status: JudgeStatus
    n_units: int
    confusion: dict[tuple[str, str], int]
    order: OrderEffect
    length: LengthEffect
    statement: str


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


def _zero_disagreement_interval(pairs: list[tuple[str, str]]) -> Interval:
    """Exact bound for the case a resampling bootstrap cannot speak to.

    With zero observed disagreements every resample yields alpha = 1.0, so a percentile
    bootstrap would publish "alpha = 1.000 [1.000, 1.000]" -- zero uncertainty at exactly the
    point the claim is strongest. That is audit H5, the same failure `stats.bootstrap._interval`
    already guards against for accuracy, and it must not reappear here.

    For two raters who both rated every unit, `Do` is the per-unit disagreement proportion, so
    0 disagreements out of n carries the exact one-sided Clopper-Pearson upper bound
    `Do_high = 1 - (1-confidence)**(1/n)` (from P(X=0 | p) = (1-p)**n = 1-confidence -- the
    identical formula `stats.bootstrap` uses for its own constant-data branch). `De` is a
    function of the observed marginals and is held at its observed value, which is what makes
    this a bound on alpha rather than a bootstrap; `alpha_low = 1 - Do_high/De`, floored at
    -1.0, alpha's lower limit.
    """
    n = len(pairs)
    _, de = disagreement(_ratings(pairs))
    do_high = 1.0 - (1.0 - CONFIDENCE) ** (1.0 / n)
    return Interval(
        point=1.0,
        low=max(-1.0, 1.0 - do_high / de),
        high=1.0,
        n=n,
        method="clopper-pearson-exact-on-disagreement",
    )


def _alpha_interval(
    pairs: list[tuple[str, str]], *, alpha: float, seed: int, n_resamples: int
) -> Interval:
    """Percentile bootstrap of *alpha itself*, resampling whole units with replacement.

    The original implementation bootstrapped the raw agreement rate and published the result
    as alpha's interval. Alpha is chance-corrected and the raw rate is not, so the two diverge
    hard under class imbalance: on a 60-unit fixture where the judge says EQUIVALENT every
    time and the human agrees half of it, alpha = -0.322 while the raw-rate interval is
    [0.373, 0.627] -- a published "alpha [low, high]" sentence whose interval did not contain
    its own point estimate. CLAUDE.md rules 2 and 3 both require the interval to describe the
    uncertainty of the number it is attached to, and the number driving the accept/reject
    decision is alpha.

    Percentile rather than BCa: BCa needs a statistic scipy can jackknife across an axis, and
    alpha is not that shape. The method string says which was used rather than borrowing the
    BCa label the accuracy intervals carry.
    """
    n = len(pairs)
    if all(judge == human for judge, human in pairs):
        return _zero_disagreement_interval(pairs)

    rng = np.random.default_rng(seed)
    resampled = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        draw = [pairs[k] for k in rng.integers(0, n, size=n)]
        try:
            resampled[i] = krippendorff_alpha(_ratings(draw))
        except ValueError:
            # This resample happened to draw only agreeing units of a single category, so both
            # observed and expected disagreement are zero and alpha is 0/0. `cohens_kappa`
            # already publishes that degenerate case as perfect agreement (its `pe == 1.0`
            # branch); matching it keeps the resample in the distribution, where dropping it
            # would bias the interval upward by discarding only its extreme.
            resampled[i] = 1.0

    tail = (1.0 - CONFIDENCE) / 2.0 * 100.0
    low, high = np.percentile(resampled, [tail, 100.0 - tail])
    return Interval(
        point=alpha, low=float(low), high=float(high), n=n, method="unit-bootstrap-percentile"
    )


def assess(  # noqa: PLR0913 -- one keyword added to a plan-frozen positional signature
    field_type: str,
    judge_verdicts: dict[str, str],
    human_verdicts: dict[str, str],
    samples: list[Sample],
    *,
    seed: int,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
) -> AgreementReport:
    units = sorted(judge_verdicts.keys() & human_verdicts.keys())
    if not units:
        raise ValueError("no overlapping units")

    pairs = [(judge_verdicts[u], human_verdicts[u]) for u in units]
    alpha = krippendorff_alpha(_ratings(pairs))
    alpha_ci = _alpha_interval(pairs, alpha=alpha, seed=seed, n_resamples=n_resamples)
    confusion = confusion_matrix(
        [judge_verdicts[u] for u in units], [human_verdicts[u] for u in units]
    )
    order = order_effect(samples)
    length = length_effect(samples)

    n_units = len(units)
    status = JudgeStatus.ACCEPTED if alpha >= REJECTION_THRESHOLD else JudgeStatus.REJECTED
    low, high = alpha_ci.low, alpha_ci.high
    if status is JudgeStatus.ACCEPTED:
        statement = (
            f"Judge-human agreement on {field_type}: Krippendorff's alpha = {alpha:.3f} "
            f"[{low:.3f}, {high:.3f}], n={n_units}. Above the pre-registered threshold of "
            f"{REJECTION_THRESHOLD}; used for headline scoring."
        )
    else:
        statement = (
            f"Judge-human agreement on {field_type}: Krippendorff's alpha = {alpha:.3f} "
            f"[{low:.3f}, {high:.3f}], n={n_units}. Below the pre-registered threshold of "
            f"{REJECTION_THRESHOLD}; this field type is not used for headline scoring and is "
            f"reported as not measured."
        )

    return AgreementReport(
        field_type=field_type,
        alpha=alpha,
        alpha_ci=alpha_ci,
        status=status,
        n_units=n_units,
        confusion=confusion,
        order=order,
        length=length,
        statement=statement,
    )


def record_decision(
    con: duckdb.DuckDBPyConnection, report: AgreementReport, *, rubric_version: str
) -> None:
    """Persist one `assess` result to `judge_decisions`, the table `matrix.build` joins.

    Without this the exclusion in `matrix.build._slot_accuracy` could only ever take its
    `jd.status IS NULL` branch: nothing wrote the table outside a test fixture, so a rejected
    judge's verdicts still reached the headline number and spec section 8.2's guarantee -- "a
    vendor cannot claim they were scored by a bad judge, because they were not" -- held only on
    the read side.

    `JudgeStatus` renders uppercase; the column's `CHECK (status IN ('accepted','rejected'))`
    and `build.py`'s `!= 'rejected'` comparison are both lowercase, so `.lower()` here is load-
    bearing in two directions at once -- without it the insert is rejected outright, and were
    the CHECK ever relaxed the exclusion would silently stop matching.

    `field_type` is the table's primary key: it holds the *current* decision per field type, so
    re-assessing after collecting more labels replaces that row rather than failing. The
    superseded decision is not lost -- both statements publish (spec section 8.2) and the
    published record is the changelog.
    """
    con.execute(
        "INSERT OR REPLACE INTO judge_decisions VALUES (?,?,?,?,?,?,?,?,?)",
        [
            report.field_type,
            rubric_version,
            report.alpha,
            report.alpha_ci.low,
            report.alpha_ci.high,
            report.n_units,
            REJECTION_THRESHOLD,
            report.status.value.lower(),
            datetime.now(UTC),
        ],
    )
