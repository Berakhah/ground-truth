import pytest

from ground_truth.graders.judge.aggregate import (
    JudgeVerdict,
    Sample,
    length_effect,
    majority_vote,
    order_effect,
    parse_judgement,
)


def s(order: int, raw: str, length: int = 20) -> Sample:
    return Sample(presentation_order=order, raw=raw, observed_length=length)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("EQUIVALENT", JudgeVerdict.EQUIVALENT),
        ("  equivalent \n", JudgeVerdict.EQUIVALENT),
        ("NOT_EQUIVALENT", JudgeVerdict.NOT_EQUIVALENT),
        ("not_equivalent", JudgeVerdict.NOT_EQUIVALENT),
        ("The answer is EQUIVALENT.", JudgeVerdict.EQUIVALENT),
        ("maybe?", JudgeVerdict.INCONCLUSIVE),
        ("", JudgeVerdict.INCONCLUSIVE),
    ],
)
def test_parse_judgement(raw, expected):
    assert parse_judgement(raw) == expected


def test_majority_of_three_wins():
    assert majority_vote(
        [s(0, "EQUIVALENT"), s(1, "EQUIVALENT"), s(0, "NOT_EQUIVALENT")]
    ) is JudgeVerdict.EQUIVALENT


def test_tie_yields_inconclusive():
    samples = [s(0, "EQUIVALENT"), s(1, "NOT_EQUIVALENT"), s(0, "?")]
    assert majority_vote(samples) is JudgeVerdict.INCONCLUSIVE, "never resolve a tie by coin flip"


def test_all_inconclusive_yields_inconclusive():
    assert majority_vote([s(0, "?"), s(1, "?"), s(0, "?")]) is JudgeVerdict.INCONCLUSIVE


def test_fewer_than_three_samples_raises():
    with pytest.raises(ValueError, match="at least 3"):
        majority_vote([s(0, "EQUIVALENT"), s(1, "EQUIVALENT")])


def test_order_effect_is_zero_when_orders_agree():
    samples = [s(0, "EQUIVALENT"), s(1, "EQUIVALENT"), s(0, "EQUIVALENT"), s(1, "EQUIVALENT")]
    assert order_effect(samples).difference == 0.0


def test_order_effect_detects_position_bias():
    effect = order_effect([s(0, "EQUIVALENT")] * 10 + [s(1, "NOT_EQUIVALENT")] * 10)
    assert effect.difference == pytest.approx(1.0)
    assert effect.n == 20  # noqa: PLR2004


def test_order_effect_requires_both_orders():
    with pytest.raises(ValueError, match="both presentation orders"):
        order_effect([s(0, "EQUIVALENT")] * 5)


def test_length_effect_returns_five_quintiles():
    effect = length_effect([s(i % 2, "EQUIVALENT", length=i) for i in range(50)])
    assert len(effect.quintile_rates) == 5 and effect.n == 50  # noqa: PLR2004


def test_length_effect_detects_verbosity_bias():
    short = [s(0, "NOT_EQUIVALENT", length=i) for i in range(25)]
    long_ = [s(1, "EQUIVALENT", length=100 + i) for i in range(25)]
    rates = length_effect(short + long_).quintile_rates
    assert rates[0] < rates[-1], "longer outputs judged equivalent more often"


def test_length_effect_needs_at_least_five_samples():
    with pytest.raises(ValueError):
        length_effect([s(0, "EQUIVALENT")] * 3)


def test_module_performs_no_io():
    import inspect  # noqa: PLC0415

    from ground_truth.graders.judge import aggregate  # noqa: PLC0415

    source = inspect.getsource(aggregate)
    for banned in ("httpx", "requests", "open(", "duckdb"):
        assert banned not in source, "judge aggregation must be a pure phase-2 function"
