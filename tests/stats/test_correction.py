# tests/stats/test_correction.py
import random

import pytest

from ground_truth.stats.correction import Comparison, benjamini_hochberg


def test_bh_matches_worked_example():
    # Benjamini & Hochberg 1995, Table 1 (15 hypotheses); FDR 0.05 -> 4 rejections
    p_values = [
        0.0001,
        0.0004,
        0.0019,
        0.0095,
        0.0201,
        0.0278,
        0.0298,
        0.0344,
        0.0459,
        0.3240,
        0.4262,
        0.5719,
        0.6528,
        0.7590,
        1.0000,
    ]
    result = benjamini_hochberg([Comparison(f"h{i}", p) for i, p in enumerate(p_values)], fdr=0.05)
    assert sum(c.significant for c in result) == 4  # noqa: PLR2004


def test_labels_survive_correction():
    comps = [Comparison("slot-a/MONEY", 0.001), Comparison("slot-b/DATE", 0.9)]
    assert {c.label for c in benjamini_hochberg(comps)} == {"slot-a/MONEY", "slot-b/DATE"}


def test_input_order_is_preserved():
    comps = [Comparison("z", 0.9), Comparison("a", 0.001)]
    assert [c.label for c in benjamini_hochberg(comps)] == ["z", "a"]


def test_adjusted_p_is_never_below_raw_p():
    comps = [Comparison(f"h{i}", i / 20) for i in range(1, 20)]
    assert all(c.adjusted_p >= c.p_value - 1e-12 for c in benjamini_hochberg(comps))


def test_single_comparison_is_unchanged():
    result = benjamini_hochberg([Comparison("only", 0.03)])
    assert result[0].adjusted_p == pytest.approx(0.03) and result[0].significant


def test_empty_input_returns_empty():
    assert benjamini_hochberg([]) == []


def test_invalid_p_value_raises_and_names_the_comparison():
    with pytest.raises(ValueError, match="bad"):
        benjamini_hochberg([Comparison("bad", 1.5)])


@pytest.mark.slow
def test_bh_controls_fdr_under_complete_null():
    """Under the complete null, FDR = FWER, so the meaningful quantity is the proportion of
    TRIALS with any rejection.

    This test previously computed false_discoveries / (trials * per_trial) -- the
    per-comparison error rate, not the FDR. FDR is E[V / max(R,1)]. Under the complete null
    BH rejects in ~5% of trials and rejects few when it does, so that ratio came out near
    0.001 and the assertion passed for almost any procedure. A statistics test that measures
    a different quantity from the one it names is how a benchmark becomes fiction. Audit M3.
    """
    rng, trials, m = random.Random(0), 2000, 48
    any_rejection = sum(
        any(
            c.significant
            for c in benjamini_hochberg(
                [Comparison(f"h{i}", rng.random()) for i in range(m)], fdr=0.05
            )
        )
        for _ in range(trials)
    )
    rate = any_rejection / trials
    assert rate <= 0.06, f"complete-null FWER {rate:.4f} exceeds the nominal 0.05"  # noqa: PLR2004


@pytest.mark.slow
def test_bh_controls_fdr_with_true_effects_present():
    """The case that distinguishes BH from Bonferroni: 12 of 48 hypotheses non-null,
    assert the mean of V/max(R,1) over trials stays at or below 0.05."""
    rng, trials, m, n_true = random.Random(1), 2000, 48, 12
    ratios = []
    for _ in range(trials):
        comps = [Comparison(f"true{i}", rng.random() * 0.001) for i in range(n_true)]
        comps += [Comparison(f"null{i}", rng.random()) for i in range(m - n_true)]
        result = benjamini_hochberg(comps, fdr=0.05)
        rejected = [c for c in result if c.significant]
        false_ = sum(c.label.startswith("null") for c in rejected)
        ratios.append(false_ / max(len(rejected), 1))
    assert sum(ratios) / trials <= 0.05  # noqa: PLR2004
