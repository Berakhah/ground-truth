"""Judge aggregation and bias measurement.

Pure stdlib: majority-vote a judge's replicate samples into one verdict, and measure the two
biases a judge harness is required to publish -- presentation-order effect and length/verbosity
effect. No provider calls, no storage; this module only turns already-collected samples into
numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_MIN_VOTE_SAMPLES = 3
_MIN_LENGTH_SAMPLES = 5
_QUINTILES = 5


class JudgeVerdict(StrEnum):
    EQUIVALENT = "EQUIVALENT"
    NOT_EQUIVALENT = "NOT_EQUIVALENT"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class Sample:
    presentation_order: int
    raw: str
    observed_length: int


@dataclass(frozen=True)
class OrderEffect:
    order_0_rate: float
    order_1_rate: float
    difference: float
    n: int


@dataclass(frozen=True)
class LengthEffect:
    quintile_rates: list[float]
    n: int


# Corrected 2026-08-29 (audit H4): the substring form ("NOT_EQUIVALENT" in text before
# "EQUIVALENT" in text) inverts the verdict on any prose negation ("not equivalent", "They are
# not equivalent.", "NOT EQUIVALENT", "Not-equivalent" all parsed as EQUIVALENT). Anchor on word
# boundaries instead and tolerate space/hyphen/underscore between NOT and EQUIVALENT.
_TOKEN = re.compile(r"\bNOT[\s_\-]?EQUIVALENT\b|\bEQUIVALENT\b")


def parse_judgement(raw: str) -> JudgeVerdict:
    hits = {
        ("NOT_EQUIVALENT" if m.startswith("NOT") else "EQUIVALENT")
        for m in _TOKEN.findall(raw.strip().upper())
    }
    if len(hits) != 1:
        return JudgeVerdict.INCONCLUSIVE  # absent, or both present -> not a verdict
    return JudgeVerdict(hits.pop())


def majority_vote(samples: list[Sample]) -> JudgeVerdict:
    if len(samples) < _MIN_VOTE_SAMPLES:
        raise ValueError("at least 3 samples required")
    verdicts = [parse_judgement(s.raw) for s in samples]
    equivalent = verdicts.count(JudgeVerdict.EQUIVALENT)
    not_equivalent = verdicts.count(JudgeVerdict.NOT_EQUIVALENT)
    if equivalent > not_equivalent:
        return JudgeVerdict.EQUIVALENT
    if not_equivalent > equivalent:
        return JudgeVerdict.NOT_EQUIVALENT
    return JudgeVerdict.INCONCLUSIVE  # tie, including 0-0 (no non-inconclusive samples)


def _equivalent_rate(samples: list[Sample]) -> float:
    if not samples:
        return 0.0
    verdicts = [parse_judgement(s.raw) for s in samples]
    return verdicts.count(JudgeVerdict.EQUIVALENT) / len(verdicts)


def order_effect(samples: list[Sample]) -> OrderEffect:
    orders = {s.presentation_order for s in samples}
    if 0 not in orders or 1 not in orders:
        raise ValueError("both presentation orders must be present")
    order_0 = [s for s in samples if s.presentation_order == 0]
    order_1 = [s for s in samples if s.presentation_order == 1]
    rate_0 = _equivalent_rate(order_0)
    rate_1 = _equivalent_rate(order_1)
    return OrderEffect(
        order_0_rate=rate_0, order_1_rate=rate_1, difference=abs(rate_0 - rate_1), n=len(samples)
    )


def _split_into_quintiles(samples: list[Sample]) -> list[list[Sample]]:
    """Split into 5 chunks as equal as possible (leading chunks absorb the remainder)."""
    quotient, remainder = divmod(len(samples), _QUINTILES)
    chunks = []
    start = 0
    for i in range(_QUINTILES):
        end = start + quotient + (1 if i < remainder else 0)
        chunks.append(samples[start:end])
        start = end
    return chunks


def length_effect(samples: list[Sample]) -> LengthEffect:
    if len(samples) < _MIN_LENGTH_SAMPLES:
        raise ValueError("at least 5 samples required")
    ordered = sorted(samples, key=lambda s: s.observed_length)
    rates = [_equivalent_rate(chunk) for chunk in _split_into_quintiles(ordered)]
    return LengthEffect(quintile_rates=rates, n=len(samples))
