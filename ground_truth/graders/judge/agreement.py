"""Judge-versus-human agreement, chained to the pre-registered rejection threshold.

Pure stdlib + the stats/aggregate modules already in this repo -- no I/O, no gateway imports,
same constraint as `graders.judge.aggregate` (Task 25). `docs/analysis-plan.md`'s "Judge
rejection threshold" section freezes the number below; do not change it without also bumping
that document's `plan_version` (`test_threshold_matches_the_pre_registered_plan` enforces the
pairing so the threshold cannot be nudged after seeing the agreement data).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ground_truth.graders.judge.aggregate import (
    LengthEffect,
    OrderEffect,
    Sample,
    length_effect,
    order_effect,
)
from ground_truth.stats.agreement import confusion_matrix, krippendorff_alpha
from ground_truth.stats.bootstrap import Interval, cluster_bootstrap_ci

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


def assess(
    field_type: str,
    judge_verdicts: dict[str, str],
    human_verdicts: dict[str, str],
    samples: list[Sample],
    *,
    seed: int,
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
    agreement = [(u, judge_verdicts[u] == human_verdicts[u]) for u in units]
    alpha_ci = cluster_bootstrap_ci(agreement, seed=seed)
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
