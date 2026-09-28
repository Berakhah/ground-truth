"""Drift detection for the scheduled regression watch.

Detection is a statistics problem, not a threshold problem (`04`, "Watch for"). Each look is
tested on that look's sweep alone against the quarter's fixed baseline (analysis plan v2). Each
cell's per-look p-value is Šidák-adjusted across the 13-look calendar, then Benjamini-Hochberg is
applied across every cell tested at this look; `detected` is BH-significance of the adjusted p.
The alert **is** the sentence: it states the test, the boundary and every p-value, and a null
result states the minimum detectable effect rather than implying absence of drift.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

from ground_truth.stats.bootstrap import Interval, cluster_bootstrap_ci
from ground_truth.stats.correction import Comparison, benjamini_hochberg
from ground_truth.stats.mde import describe_mde_two_sample
from ground_truth.stats.sequential import SequentialResult, check_look, evaluate_look, format_p

Z_95 = norm.ppf(0.975)  # ~1.959964, matching cluster_bootstrap_ci's fixed 95% confidence level


@dataclass(frozen=True)
class Alert:
    slot: str
    field_type: str
    baseline: Interval
    current: Interval
    z: float
    adjusted_p: float
    look: int
    total_looks: int
    detected: bool
    statement: str


def _se(interval: Interval) -> float:
    # Each side's standard error, backed out of its own bootstrap interval width rather than a
    # pooled-binomial estimate -- a pooled proportion test ignores clustering and would
    # understate variance, exactly what cluster_bootstrap_ci exists to correct for.
    return float((interval.high - interval.low) / (2 * Z_95))


def _filter_to_cohort(obs: list[tuple[str, bool]], cohort: set[str]) -> list[tuple[str, bool]]:
    return [o for o in obs if o[0] in cohort]


def detect_drift(  # noqa: PLR0913 -- each param is a distinct, required input
    baseline: dict[tuple[str, str], list[tuple[str, bool]]],
    current: dict[tuple[str, str], list[tuple[str, bool]]],
    *,
    look: int,
    total_looks: int,
    seed: int,
    cohort: set[str] | None = None,
    cross_release: bool = False,
) -> list[Alert]:
    """Compare the quarter's fixed `baseline` against **this look's sweep only**.

    Analysis plan v2: a silent provider update is a change at one point in time, so each look
    is tested on its own data. v1 pooled every look since the start of the quarter, which
    diluted a change at look 10 by nine looks of the old model (code review 2026-09-27 #2,
    finding 2). Only cells with data at this look are tested; a cell that produced nothing is
    absent from the result rather than re-tested on stale data under this look's number.
    """
    if not isinstance(current, dict):
        raise TypeError(
            "detect_drift takes this look's observations only, as one dict keyed by "
            "(slot, field_type) -- not a per-look history to pool (analysis plan v2)"
        )
    # Checked before anything else so a bad look raises even when no cell has data.
    check_look(look, total_looks)
    if cross_release and cohort is None:
        raise ValueError(
            "cross_release=True requires an explicit cohort: comparing across a private-split "
            "rotation without restricting to the shared cohort would attribute cohort churn to "
            "model drift (Task 51)."
        )

    keys = sorted(current)
    n_comparisons = len(keys)

    tested: list[tuple[Interval, Interval, float]] = []
    sequential: list[SequentialResult] = []
    comparisons: list[Comparison] = []
    n_rotated_by_key: dict[tuple[str, str], int] = {}
    tested_obs: dict[tuple[str, str], tuple[list[tuple[str, bool]], list[tuple[str, bool]]]] = {}
    for key in keys:
        baseline_obs = baseline[key]  # raise KeyError on a miss -- never skip a comparison
        current_obs = current[key]
        if cohort is not None:
            n_rotated_by_key[key] = len({i for i, _ in baseline_obs} - cohort)
            baseline_obs = _filter_to_cohort(baseline_obs, cohort)
            current_obs = _filter_to_cohort(current_obs, cohort)
        tested_obs[key] = (baseline_obs, current_obs)
    # Checked on what is actually tested -- after the cohort filter, on both sides -- and for
    # every cell before any is tested, so one error names them all. Checking `current` before
    # filtering missed a cell the filter emptied and an empty baseline, both of which crashed
    # the whole look inside the bootstrap, unnamed (code review 2026-09-28 #3).
    empty = [
        f"{side} of {slot}/{field}"
        for (slot, field), sides in sorted(tested_obs.items())
        for side, side_obs in zip(("baseline", "current"), sides, strict=True)
        if not side_obs
    ]
    if empty:
        raise ValueError(
            f"no observations to test at look {look} for the {', '.join(empty)}"
            + (" after restricting to the cohort" if cohort is not None else "")
            + ": leave a cell that ran nothing out of `current` -- it is not tested at this "
            "look, rather than crashing it"
        )
    for key in keys:
        baseline_obs, current_obs = tested_obs[key]
        baseline_interval = cluster_bootstrap_ci(baseline_obs, seed=seed)
        current_interval = cluster_bootstrap_ci(current_obs, seed=seed)
        z = (current_interval.point - baseline_interval.point) / math.sqrt(
            _se(current_interval) ** 2 + _se(baseline_interval) ** 2
        )
        tested.append((baseline_interval, current_interval, z))
        seq = evaluate_look(z, look, total_looks)
        sequential.append(seq)
        slot, field_type = key
        # The Šidák-adjusted p, not the raw one, is what BH corrects across cells (plan v2).
        comparisons.append(Comparison(label=f"{slot}/{field_type}", p_value=seq.adjusted_p))

    # Positional pairing, not a label-keyed dict: `comparisons` was appended in exact lockstep
    # with `keys` above, with no filtering in between, so the correspondence is already
    # guaranteed by construction. A label-keyed dict would silently collide (and misattribute a
    # corrected p-value) if two distinct (slot, field_type) pairs ever produced the same
    # f"{slot}/{field_type}" string -- e.g. a slot or field_type containing "/".
    alerts: list[Alert] = []
    for key, (baseline_interval, current_interval, z), seq, cc in zip(
        keys, tested, sequential, benjamini_hochberg(comparisons), strict=True
    ):
        slot, field_type = key
        detected = cc.significant
        bh = (
            f"Benjamini-Hochberg adjusted {format_p(cc.adjusted_p)} across {n_comparisons} "
            "comparisons"
        )
        prefix = (
            f"{slot}/{field_type}: {baseline_interval.point:.3f} "
            f"[{baseline_interval.low:.3f}, {baseline_interval.high:.3f}] -> "
            f"{current_interval.point:.3f} "
            f"[{current_interval.low:.3f}, {current_interval.high:.3f}]. "
        )
        if detected:
            statement = prefix + (
                f"Change detected at look {look} of {total_looks}: |z| = {abs(z):.3f} exceeds "
                f"{seq.test}; {bh}."
            )
        else:
            relation = "exceeds" if seq.reject else "is within"
            statement = (
                prefix
                + (
                    f"No change detected at look {look} of {total_looks}: |z| = {abs(z):.3f} "
                    f"{relation} {seq.test}; {bh}. "
                )
                + describe_mde_two_sample(
                    baseline_interval.n,
                    current_interval.n,
                    math.hypot(_se(baseline_interval), _se(current_interval)),
                    alpha=seq.alpha_look,
                    n_comparisons=n_comparisons,
                )
                + " This minimum detectable effect is for one look's sweep at the per-look alpha."
            )

        if cohort is not None:
            statement += (
                f" Comparison restricted to the {len(cohort)} private items present in both "
                f"releases; {n_rotated_by_key[key]} items rotated between them and are excluded."
            )

        alerts.append(
            Alert(
                slot=slot,
                field_type=field_type,
                baseline=baseline_interval,
                current=current_interval,
                z=z,
                adjusted_p=cc.adjusted_p,
                look=look,
                total_looks=total_looks,
                detected=detected,
                statement=statement,
            )
        )

    return alerts
