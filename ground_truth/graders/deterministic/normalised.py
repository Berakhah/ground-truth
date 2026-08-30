from __future__ import annotations

import re
import string
import unicodedata
from datetime import datetime

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import ItemField
from ground_truth.graders.base import Verdict

GRADER_ID = "normalised"
GRADER_VERSION = "1"

# Sentinel returned by iso_date (and threaded through normalise/grade_normalised) when a
# slash-formatted date genuinely cannot be resolved between day-first and month-first.
AMBIGUOUS = "AMBIGUOUS_DATE"

_LEGAL_SUFFIXES = ("Inc.", "LLC", "Ltd.", "Pty Ltd", "GmbH", "Co.", "Corp.")
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)
_LEADING_ZEROS = re.compile(r"(?<=\D)0+(?=\d)|^0+(?=\d)")
_SLASH_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y")


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _strip_legal_suffix(value: str) -> str:
    stripped = value.rstrip()
    for suffix in _LEGAL_SUFFIXES:
        if stripped.casefold().endswith(suffix.casefold()):
            return stripped[: len(stripped) - len(suffix)].rstrip()
    return value


def _resolve_slash_date(text: str) -> str:
    interpretations = set()
    for fmt in ("%d/%m/%Y", "%m/%d/%Y"):
        try:
            interpretations.add(datetime.strptime(text, fmt).date())
        except ValueError:
            continue
    if not interpretations:
        raise ValueError(f"unparseable date: {text!r}")
    if len(interpretations) > 1:
        return AMBIGUOUS
    return interpretations.pop().isoformat()


def _iso_date(value: str) -> str:
    text = value.strip()
    if _SLASH_DATE.match(text):
        return _resolve_slash_date(text)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {value!r}")


def normalise(value: str, steps: list[str]) -> str:
    result = value
    for step in steps:
        if result == AMBIGUOUS:
            return AMBIGUOUS
        if step == "casefold":
            result = result.casefold()
        elif step == "strip_accents":
            result = _strip_accents(result)
        elif step == "strip_punctuation":
            result = result.translate(_PUNCT_TABLE)
        elif step == "strip_legal_suffix":
            result = _strip_legal_suffix(result)
        elif step == "strip_leading_zeros":
            result = _LEADING_ZEROS.sub("", result)
        elif step == "iso_date":
            result = _iso_date(result)
        else:
            raise ValueError(f"unknown normalisation step: {step!r}")
    return result


def grade_normalised(field: ItemField, observed: str | None, rule: RubricRule) -> Verdict:
    def verdict(correct: bool, reason: str) -> Verdict:
        return Verdict(
            correct=correct, reason=reason, grader_id=GRADER_ID, grader_version=GRADER_VERSION
        )

    if observed is None:
        return verdict(False, "no output for field")
    try:
        want = normalise(field.expected_value, rule.normalisation)
        got = normalise(observed, rule.normalisation)
    except ValueError as exc:
        return verdict(False, str(exc))
    if AMBIGUOUS in (want, got):
        return verdict(False, "ambiguous date: day/month order cannot be resolved")
    if got == want:
        return verdict(True, "normalised match")
    for pair in rule.acceptable_variants:
        canonical, _, variant = pair.partition("=")
        try:
            variant_forms = {
                normalise(canonical, rule.normalisation),
                normalise(variant, rule.normalisation),
            }
        except ValueError:
            continue
        if got in variant_forms:
            return verdict(True, f"matched declared variant {pair!r}")
    return verdict(False, f"expected {want!r}, got {got!r}")
