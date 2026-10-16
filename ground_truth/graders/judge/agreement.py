"""Judge-versus-human agreement, chained to the pre-registered rejection threshold.

No gateway imports, same constraint as `graders.judge.aggregate` (Task 25). `assess` is a pure
function; `record_decision` is this module's one writer, kept as a separate call so `assess`
stays usable with no store at all. `docs/analysis-plan.md`'s "Judge rejection threshold"
section freezes the number below; do not change it without also bumping that document's
`plan_version` (`test_threshold_matches_the_pre_registered_plan` enforces the pairing so the
threshold cannot be nudged after seeing the agreement data).
"""

from __future__ import annotations

import math
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
    AlphaInterval,
    alpha_bootstrap_ci,
    confusion_matrix,
    krippendorff_alpha,
)

REJECTION_THRESHOLD: float = 0.667


class JudgeStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class AgreementReport:
    field_type: str
    alpha: float
    alpha_ci: AlphaInterval
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

    verdicts = {judge_verdicts[u] for u in units} | {human_verdicts[u] for u in units}
    if len(verdicts) == 1:
        return _undefined_alpha_report(field_type, units, verdicts.pop(), samples)

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
    low, high = alpha_ci.low, alpha_ci.high
    estimable = math.isfinite(low) and math.isfinite(high)
    # An interval that could not be estimated (every resample 0/0) is a judge we cannot defend,
    # whatever its point estimate (CLAUDE.md rule 3).
    accepted = estimable and alpha >= REJECTION_THRESHOLD
    status = JudgeStatus.ACCEPTED if accepted else JudgeStatus.REJECTED
    head = f"Judge-human agreement on {field_type}: Krippendorff's alpha = {alpha:.3f} "
    if not estimable:
        head += f"(interval could not be estimated: {alpha_ci.method}), n={n_units}."
    elif alpha_ci.n_undefined_excluded:
        # Excluding 0/0 draws drops the most-agreeing resamples, so the interval is conditional
        # and sits low; said here because this sentence is what gets published. Decided and
        # worded from the count, not from `method`, so rewording that string cannot drop it
        # (code review 2026-09-28 #6).
        head += (
            f"[{low:.3f}, {high:.3f}], n={n_units} ({alpha_ci.n_undefined_excluded} of "
            f"{alpha_ci.n_resamples} undefined resamples excluded; the interval is conditional "
            f"on alpha being defined)."
        )
    else:
        head += f"[{low:.3f}, {high:.3f}], n={n_units}."
    if accepted:
        statement = (
            f"{head} Above the pre-registered threshold of {REJECTION_THRESHOLD}; used for "
            f"headline scoring."
        )
    else:
        statement = (
            f"{head} Below the pre-registered threshold of {REJECTION_THRESHOLD}; this field "
            f"type is not used for headline scoring and is reported as not measured."
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


def _undefined_alpha_report(
    field_type: str, units: list[str], verdict: str, samples: list[Sample]
) -> AgreementReport:
    """Both raters gave every unit the same single verdict: expected disagreement is zero and
    alpha is 0/0. A judge that always answers `verdict` is indistinguishable from a perfect one
    on this sample, so it cannot clear the threshold (CLAUDE.md rule 3: a judge we cannot
    defend falls back). Raising instead would leave no `judge_decisions` row: `matrix.build`
    would still keep the judge out of the headline (no accepted decision), but nothing would be
    published to say it was assessed or why it does not score.

    NaN, not 1.0: publishing 1.0 as this sample's alpha would be a claim the data cannot
    support. `alpha_bootstrap_ci` follows the same convention for its resamples, excluding a
    0/0 draw rather than scoring it as perfect agreement.
    """
    n_units = len(units)
    nan = math.nan
    return AgreementReport(
        field_type=field_type,
        alpha=nan,
        alpha_ci=AlphaInterval(
            point=nan,
            low=nan,
            high=nan,
            n=n_units,
            method="undefined",
            n_undefined_excluded=0,  # no bootstrap was run
            n_resamples=0,
        ),
        status=JudgeStatus.REJECTED,
        n_units=n_units,
        confusion={(verdict, verdict): n_units},
        order=order_effect(samples),
        length=length_effect(samples),
        statement=(
            f"Judge-human agreement on {field_type}: Krippendorff's alpha is undefined, n={n_units}"
            f" -- judge and human gave every unit the same verdict ({verdict}), so this sample "
            f"cannot distinguish the judge from one that always answers {verdict}. Treated as "
            f"below the pre-registered threshold of {REJECTION_THRESHOLD}; this field type is "
            f"not used for headline scoring and is reported as not measured."
        ),
    )


def record_decision(
    con: duckdb.DuckDBPyConnection,
    report: AgreementReport,
    *,
    rubric_version: str,
    judge_slot: str,
) -> None:
    """Persist one `assess` result for one judge to `judge_decisions`, the table
    `matrix.build` joins.

    `matrix.build._slot_accuracy` counts a `judge:<judge_slot>` verdict only when this table
    holds an accepted decision for that judge on that field type, so an unassessed judge never
    scores. Spec section 8.2's guarantee -- "a vendor cannot claim they were scored by a bad
    judge, because they were not" -- needs this writer as much as that reader.

    `JudgeStatus` renders uppercase; the column's `CHECK (status IN ('accepted','rejected'))`
    and `build.py`'s `= 'accepted'` comparison are both lowercase, so `.lower()` here is load-
    bearing in two directions at once -- without it the insert is rejected outright, and were
    the CHECK ever relaxed no judge would ever be admitted.

    `(field_type, judge_slot)` is the table's primary key: it holds the *current* decision per
    judge per field type, so re-assessing one judge after collecting more labels replaces that
    judge's row only. The superseded decision is not lost -- both statements publish (spec
    section 8.2) and the published record is the changelog.
    """
    con.execute(
        "INSERT OR REPLACE INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, "
        "alpha_low, alpha_high, n_units, threshold, status, decided_at, statement, "
        "alpha_method) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            report.field_type,
            judge_slot,
            rubric_version,
            report.alpha,
            report.alpha_ci.low,
            report.alpha_ci.high,
            report.n_units,
            REJECTION_THRESHOLD,
            report.status.value.lower(),
            datetime.now(UTC),
            report.statement,
            report.alpha_ci.method,
        ],
    )
