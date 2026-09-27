"""Drift detection for the scheduled regression watch.

Detection is a statistics problem, not a threshold problem (`04`, "Watch for"). A single look
at one comparison is exactly the setup that produces alert spam, then muted alerts, then a
missed real regression -- so `detected` requires BOTH the pre-registered O'Brien-Fleming
sequential boundary to be crossed at this look AND the Benjamini-Hochberg-adjusted p-value
(corrected across every comparison made in this call) to be significant. The alert **is** the
sentence: a null result states the minimum detectable effect rather than implying absence of
drift, per `describe_mde`'s own closing line.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from scipy.stats import norm

from ground_truth.stats.bootstrap import Interval, cluster_bootstrap_ci
from ground_truth.stats.correction import Comparison, benjamini_hochberg
from ground_truth.stats.mde import describe_mde
from ground_truth.stats.sequential import evaluate_look

# describe_mde's discordance_rate must be in (0, 1] -- see the identical floor and reasoning in
# ground_truth/triage/report.py's _mde_caveat for the "no true discordance rate available" case.
_MIN_DISCORDANCE_RATE = 0.01

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


def _discordance_rate(
    baseline: dict[tuple[str, str], list[tuple[str, bool]]],
    current: dict[tuple[str, str], list[tuple[str, bool]]],
    key: tuple[str, str],
    current_interval: Interval,
) -> tuple[int, float]:
    baseline_by_id = dict(baseline[key])
    current_by_id = dict(current[key])
    paired_ids = baseline_by_id.keys() & current_by_id.keys()
    if paired_ids:
        n_items = len(paired_ids)
        disagreements = sum(1 for i in paired_ids if baseline_by_id[i] != current_by_id[i])
        return n_items, max(disagreements / n_items, _MIN_DISCORDANCE_RATE)
    # No id overlap -- shouldn't occur given the regression watch's anchor-subset design
    # (Task 51), but must not crash. Same proxy as report.py's _mde_caveat.
    return current_interval.n, max(1 - current_interval.point, _MIN_DISCORDANCE_RATE)


def _filter_to_cohort(obs: list[tuple[str, bool]], cohort: set[str]) -> list[tuple[str, bool]]:
    return [o for o in obs if o[0] in cohort]


def _pool(
    looks: Sequence[dict[tuple[str, str], list[tuple[str, bool]]]],
) -> dict[tuple[str, str], list[tuple[str, bool]]]:
    pooled: dict[tuple[str, str], list[tuple[str, bool]]] = {}
    for observations in looks:
        for key, obs in observations.items():
            pooled.setdefault(key, []).extend(obs)
    return pooled


def detect_drift(  # noqa: PLR0913 -- each param is a distinct, required input
    baseline: dict[tuple[str, str], list[tuple[str, bool]]],
    current_by_look: Sequence[dict[tuple[str, str], list[tuple[str, bool]]]],
    *,
    look: int,
    total_looks: int,
    seed: int,
    cohort: set[str] | None = None,
    cross_release: bool = False,
) -> list[Alert]:
    """Compare `baseline` against everything observed so far this quarter.

    **Input must be cumulative.** `current_by_look[k]` holds the observations from look k+1,
    and the list must cover every look from 1 to `look` -- they are pooled here, so the z at
    look k is computed on all data accumulated through look k. `C_OBF_13_LOOKS` was calibrated
    for exactly that process, corr(Z_j, Z_k) = sqrt(t_j/t_k); fed only the current look's run,
    the 13 looks are independent and the family-wise type-I error is ~0.12, not 0.05 (stats
    review 2026-09-27, finding 2). A list of the wrong length raises rather than guessing which
    looks it holds. A look that produced nothing for a key contributes an empty dict entry.

    Pooling re-runs of the *same* anchor items adds replicates to existing item clusters rather
    than new clusters, so information grows more slowly than t = k/13 and successive z's are
    more correlated than sqrt(t_j/t_k). That direction makes the boundary conservative (fewer
    false alarms, lower power), never anti-conservative.
    """
    if len(current_by_look) != look:
        raise ValueError(
            f"detect_drift needs cumulative input: one observation dict per look from 1 to "
            f"{look}, got {len(current_by_look)}. The O'Brien-Fleming constant is calibrated for "
            "a z on data accumulated across looks; this look's run alone inflates type-I error."
        )
    current = _pool(current_by_look)

    if cross_release and cohort is None:
        raise ValueError(
            "cross_release=True requires an explicit cohort: comparing across a private-split "
            "rotation without restricting to the shared cohort would attribute cohort churn to "
            "model drift (Task 51)."
        )

    keys = sorted(current)
    n_comparisons = len(keys)

    intervals: list[tuple[Interval, Interval]] = []
    zs: list[float] = []
    comparisons: list[Comparison] = []
    n_rotated_by_key: dict[tuple[str, str], int] = {}
    for key in keys:
        baseline_obs = baseline[key]  # raise KeyError on a miss -- never skip a comparison
        current_obs = current[key]
        if cohort is not None:
            n_rotated_by_key[key] = len({i for i, _ in baseline_obs} - cohort)
            baseline_obs = _filter_to_cohort(baseline_obs, cohort)
            current_obs = _filter_to_cohort(current_obs, cohort)
        baseline_interval = cluster_bootstrap_ci(baseline_obs, seed=seed)
        current_interval = cluster_bootstrap_ci(current_obs, seed=seed)
        intervals.append((baseline_interval, current_interval))
        z = (current_interval.point - baseline_interval.point) / math.sqrt(
            _se(current_interval) ** 2 + _se(baseline_interval) ** 2
        )
        zs.append(z)
        slot, field_type = key
        comparisons.append(
            Comparison(label=f"{slot}/{field_type}", p_value=2 * (1 - norm.cdf(abs(z))))
        )

    # Positional pairing, not a label-keyed dict: `comparisons` was appended in exact lockstep
    # with `keys` above, with no filtering in between, so the correspondence is already
    # guaranteed by construction. A label-keyed dict would silently collide (and misattribute a
    # corrected p-value) if two distinct (slot, field_type) pairs ever produced the same
    # f"{slot}/{field_type}" string -- e.g. a slot or field_type containing "/".
    alerts: list[Alert] = []
    for key, (baseline_interval, current_interval), z, cc in zip(
        keys, intervals, zs, benjamini_hochberg(comparisons), strict=True
    ):
        slot, field_type = key
        seq_result = evaluate_look(z, look, total_looks)
        detected = seq_result.reject and cc.significant

        prefix = (
            f"{slot}/{field_type}: {baseline_interval.point:.3f} "
            f"[{baseline_interval.low:.3f}, {baseline_interval.high:.3f}] -> "
            f"{current_interval.point:.3f} "
            f"[{current_interval.low:.3f}, {current_interval.high:.3f}]. "
        )
        if detected:
            statement = prefix + (
                f"Change detected at look {look} of {total_looks} (O'Brien-Fleming alpha "
                f"spending, |z| = {abs(z):.3f}; Benjamini-Hochberg adjusted p = "
                f"{cc.adjusted_p:.4f} across {n_comparisons} comparisons)."
            )
        else:
            n_items, discordance_rate = _discordance_rate(baseline, current, key, current_interval)
            statement = (
                prefix
                + (
                    f"No change detected at look {look} of {total_looks} (O'Brien-Fleming alpha "
                    f"spending; Benjamini-Hochberg adjusted p = {cc.adjusted_p:.4f}). "
                )
                + describe_mde(n_items, discordance_rate)
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
