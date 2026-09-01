import pytest

from ground_truth.stats.agreement import cohens_kappa, confusion_matrix, krippendorff_alpha


def test_perfect_agreement_is_one():
    assert cohens_kappa(["a", "b", "a"], ["a", "b", "a"]) == pytest.approx(1.0)


def test_cohens_kappa_zero_on_independent_raters():
    a = ["x"] * 50 + ["y"] * 50
    b = (["x"] * 25 + ["y"] * 25) * 2
    assert cohens_kappa(a, b) == pytest.approx(0.0, abs=0.02)


def test_cohens_kappa_matches_worked_example():
    # 2x2 table: both-yes 20, a-yes/b-no 5, a-no/b-yes 10, both-no 15
    # Po = 0.70, Pe = 0.50  ->  kappa = 0.40
    a = ["yes"] * 25 + ["no"] * 25
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
    assert cohens_kappa(a, b) == pytest.approx(0.40, abs=1e-9)


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        cohens_kappa(["a"], ["a", "b"])


def test_krippendorff_alpha_matches_hand_derivable_two_rater_table():
    """15 units, 2 raters, 13 agreements (units 6 and 15 disagree).

    Derived in the audit: coincidence total n = 30, marginals {1:9, 2:7, 3:9, 4:5},
    D_observed = 4, D_expected = 664/29 = 22.896552, alpha = 1 - (4/30)/(664/870) = 0.825301.

    This expectation was 0.743 until 2026-08-29. That figure belongs to Krippendorff's
    canonical THREE-observer, twelve-unit, missing-data example -- not to this table -- so
    the test both failed and mislabelled itself. It matters more than an ordinary wrong
    constant: alpha drives the pre-registered judge rejection threshold, so an implementer
    bending the estimator to reach 0.743 would put every published accept/reject decision
    on a broken statistic. Evidence: docs/superpowers/reviews/verify/verify_stats.py
    """
    ratings = {
        "obs_a": {
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "3",
            "5": "2",
            "6": "1",
            "7": "4",
            "8": "1",
            "9": "2",
            "10": "1",
            "11": "1",
            "12": "3",
            "13": "3",
            "14": "4",
            "15": "3",
        },
        "obs_b": {
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "3",
            "5": "2",
            "6": "2",
            "7": "4",
            "8": "1",
            "9": "2",
            "10": "1",
            "11": "1",
            "12": "3",
            "13": "3",
            "14": "4",
            "15": "4",
        },
    }
    assert krippendorff_alpha(ratings) == pytest.approx(0.8253, abs=0.0005)


def test_krippendorff_alpha_matches_published_worked_example():
    """Krippendorff's canonical nominal example: 4 observers, 12 units, WITH missing data.

    The missing-data pattern is the point -- it is the shape a partial second labeller
    produces (04 B1), and Cohen's kappa cannot consume it. Transcribed verbatim from Klaus
    Krippendorff, "Computing Krippendorff's Alpha-Reliability" (2011.1.25, updated
    2013.9.13), section C ("Nominal data, any number of observers, missing data"), hosted by
    the Annenberg School for Communication, UPenn:
    https://www.asc.upenn.edu/sites/default/files/2021-03/Computing%20Krippendorff's%20Alpha-Reliability.pdf

    The reliability data matrix there (observers A-D, units 1-12, "." = not coded):
        A: 1 2 3 3 2 1 4 1 2 . . .
        B: 1 2 3 3 2 2 4 1 2 5 . 3
        C: . 3 3 3 2 3 4 2 2 5 1 .
        D: 1 2 3 3 2 4 4 1 2 5 1 .
    7 of the 48 possible values are missing; 40 pairable values remain. Krippendorff reports
    nominal alpha = 0.743 for this table (worked twice, in sections C and E, to the same
    figure). Note: the task brief's own docstring guess of "3 observers" for this example
    was a paraphrase, not a checked fact -- the source has 4; verifying against the source
    rather than trusting that recollection is the entire point of this test.
    One worked example is not a validation -- keep both anchors.
    """
    ratings = {
        "A": {
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "3",
            "5": "2",
            "6": "1",
            "7": "4",
            "8": "1",
            "9": "2",
        },
        "B": {
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "3",
            "5": "2",
            "6": "2",
            "7": "4",
            "8": "1",
            "9": "2",
            "10": "5",
            "12": "3",
        },
        "C": {
            "2": "3",
            "3": "3",
            "4": "3",
            "5": "2",
            "6": "3",
            "7": "4",
            "8": "2",
            "9": "2",
            "10": "5",
            "11": "1",
        },
        "D": {
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "3",
            "5": "2",
            "6": "4",
            "7": "4",
            "8": "1",
            "9": "2",
            "10": "5",
            "11": "1",
        },
    }
    assert krippendorff_alpha(ratings) == pytest.approx(0.743, abs=0.005)


def test_alpha_handles_a_partial_second_rater():
    ratings = {
        "primary": {str(i): ("a" if i % 2 else "b") for i in range(100)},
        "partial": {str(i): ("a" if i % 2 else "b") for i in range(20)},
    }
    assert krippendorff_alpha(ratings) == pytest.approx(1.0, abs=1e-6)


def test_alpha_of_total_disagreement_is_negative():
    assert krippendorff_alpha({"a": {"1": "x", "2": "y"}, "b": {"1": "y", "2": "x"}}) < 0


def test_alpha_with_no_overlapping_units_raises():
    with pytest.raises(ValueError):
        krippendorff_alpha({"a": {"1": "x"}, "b": {"2": "y"}})


def test_confusion_matrix_counts_every_pair():
    m = confusion_matrix(["a", "a", "b"], ["a", "b", "b"])
    assert m[("a", "a")] == 1 and m[("a", "b")] == 1 and m[("b", "b")] == 1
