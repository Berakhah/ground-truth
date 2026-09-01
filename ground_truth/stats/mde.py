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
        f"({power:.0%} power, alpha={alpha}, Bonferroni-corrected across {n_comparisons} "
        f"comparisons). A null result means no difference larger than that was detectable — "
        f"not that none exists."
    )
