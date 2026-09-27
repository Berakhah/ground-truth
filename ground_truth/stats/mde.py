from __future__ import annotations

import math

from scipy.stats import norm


def mde_paired_binary(
    n_items: int,
    discordance_rate: float,
    *,
    alpha: float = 0.05,
    power: float = 0.8,
    n_comparisons: int = 1,
) -> float:
    if n_items <= 0:
        raise ValueError("n_items must be positive")
    if not 0.0 < discordance_rate <= 1.0:
        raise ValueError("discordance_rate must be in (0, 1]")
    if n_comparisons < 1:
        raise ValueError("n_comparisons must be at least 1")
    adjusted_alpha = alpha / n_comparisons  # Bonferroni: conservative and knowable in advance
    z_alpha = float(norm.ppf(1 - adjusted_alpha / 2))
    z_beta = float(norm.ppf(power))
    return (z_alpha + z_beta) * math.sqrt(discordance_rate / n_items)


def describe_mde(
    n_items: int,
    discordance_rate: float,
    *,
    alpha: float = 0.05,
    power: float = 0.8,
    n_comparisons: int = 1,
) -> str:
    delta = mde_paired_binary(
        n_items, discordance_rate, alpha=alpha, power=power, n_comparisons=n_comparisons
    )
    return (
        f"At n={n_items} items with a {discordance_rate:.0%} discordance rate, this comparison "
        f"can detect a difference of {delta * 100:.1f} percentage points or larger "
        f"({power:.0%} power, alpha={alpha:.4g}, Bonferroni-corrected across {n_comparisons} "
        f"comparisons). A null result means no difference larger than that was detectable — "
        f"not that none exists."
    )


def mde_two_sample(
    se: float,
    *,
    alpha: float = 0.05,
    power: float = 0.8,
    n_comparisons: int = 1,
) -> float:
    """MDE of a two-sided z test on a difference with standard error `se`.

    For the regression watch, whose test is z = (current - baseline) / sqrt(se_b^2 + se_c^2)
    on the two cluster-bootstrap intervals. `mde_paired_binary` is a paired McNemar formula
    and describes a different, more powerful test; used there it overstated what a null look
    could see (code review 2026-09-27 #3).
    """
    if not se > 0.0:
        raise ValueError(f"standard error must be positive, got {se}")
    if n_comparisons < 1:
        raise ValueError("n_comparisons must be at least 1")
    adjusted_alpha = alpha / n_comparisons  # Bonferroni: conservative and knowable in advance
    z_alpha = float(norm.ppf(1 - adjusted_alpha / 2))
    z_beta = float(norm.ppf(power))
    return (z_alpha + z_beta) * se


def describe_mde_two_sample(  # noqa: PLR0913 -- mirrors describe_mde plus the second n
    n_baseline: int,
    n_current: int,
    se: float,
    *,
    alpha: float = 0.05,
    power: float = 0.8,
    n_comparisons: int = 1,
) -> str:
    delta = mde_two_sample(se, alpha=alpha, power=power, n_comparisons=n_comparisons)
    return (
        f"At n={n_baseline} baseline and {n_current} current items, with the standard errors "
        f"measured at this look, this comparison can detect a difference of "
        f"{delta * 100:.1f} percentage points or larger ({power:.0%} power, alpha={alpha:.4g}, "
        f"Bonferroni-corrected across {n_comparisons} comparisons). A null result means no "
        f"difference larger than that was detectable — not that none exists."
    )
