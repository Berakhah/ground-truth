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

from ground_truth.graders.judge.aggregate import (
    LengthEffect,
    OrderEffect,
    Sample,
    length_effect,
    order_effect,
)
from ground_truth.stats.agreement import (
    BOOTSTRAP_RESAMPLES,
    alpha_bootstrap_ci,
    confusion_matrix,
    krippendorff_alpha,
)
from ground_truth.stats.bootstrap import Interval

REJECTION_THRESHOLD: float = 0.667


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

    alpha = krippendorff_alpha(
        {
            "judge": {u: judge_verdicts[u] for u in units},
            "human": {u: human_verdicts[u] for u in units},
        }
    )
    # The interval is alpha's own, bootstrapped over units -- NOT the raw agreement rate's,
    # which is what this line used to compute and publish under alpha's name. See
    # `alpha_bootstrap_ci`'s docstring for the divergence that made that a live misstatement.
    alpha_ci = alpha_bootstrap_ci(
        [(judge_verdicts[u], human_verdicts[u]) for u in units],
        seed=seed,
        n_resamples=n_resamples,
    )
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
