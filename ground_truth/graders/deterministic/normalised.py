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


class UnknownNormalisationStep(ValueError):
    """A rubric declares a normalisation step this module does not implement.

    Deliberately a ValueError subclass, not a bare one: every existing `except ValueError`
    in this module still catches it (no caller's exception-handling behaviour changes), but
    it is now possible for a caller that cares to `except UnknownNormalisationStep`
    specifically and distinguish "the rubric names a step nobody wrote code for" (a
    vocabulary bug in this module) from "a declared, implemented step just didn't match this
    value" (e.g. an unparseable date -- a normal grading outcome). Final review item 2: this
    is exactly the ambiguity that let both this bug class and its exact.py sibling (item 1)
    hide silently -- a caller had no way to tell them apart even if it had wanted to.
    """


# Sentinel returned by iso_date (and threaded through normalise/grade_normalised) when a
# slash-formatted date genuinely cannot be resolved between day-first and month-first.
AMBIGUOUS = "AMBIGUOUS_DATE"

_LEGAL_SUFFIXES = ("Inc.", "LLC", "Ltd.", "Pty Ltd", "GmbH", "Co.", "Corp.")
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)
_LEADING_ZEROS = re.compile(r"(?<=\D)0+(?=\d)|^0+(?=\d)")
_SLASH_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y")
# docs/rubric.md's DATE and PARTY_NAME steps, not this module's own vocabulary.
_ORDINAL_SUFFIX = re.compile(r"(?<=\d)(st|nd|rd|th)\b", re.IGNORECASE)
_AMPERSAND = re.compile(r"\s*&\s*")
_RESOLVED_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _strip_legal_suffix(value: str) -> str:
    stripped = value.rstrip()
    for suffix in _LEGAL_SUFFIXES:
        if stripped.casefold().endswith(suffix.casefold()):
            return stripped[: len(stripped) - len(suffix)].rstrip()
    return value


def _strip_ordinal_suffix(value: str) -> str:
    """Strips a trailing ordinal suffix after a digit (1st/2nd/3rd/4th -> 1/2/3/4).

    A no-op on a string with none.
    """
    return _ORDINAL_SUFFIX.sub("", value)


def _ampersand_to_and(value: str) -> str:
    return _AMPERSAND.sub(" and ", value)


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
    # Ordinal suffixes are stripped unconditionally here (not only via the standalone
    # strip_ordinal_suffix step) because docs/rubric.md declares DATE's steps as
    # "parse_to_iso_8601; strip_ordinal_suffix; ..." -- parse before strip. A pipeline
    # that only stripped ordinals when the step is reached would fail to parse
    # "5th Jan 2024" on the first (parsing) step, before ever reaching the second.
    text = _strip_ordinal_suffix(value.strip())
    if _SLASH_DATE.match(text):
        return _resolve_slash_date(text)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {value!r}")


def normalise(value: str, steps: list[str]) -> str:  # noqa: PLR0912 -- explicit dispatch chain
    result = value
    for step in steps:
        if result == AMBIGUOUS:
            return AMBIGUOUS
        if step == "casefold":
            result = result.casefold()
        elif step == "strip_whitespace":
            result = result.strip()
        elif step == "strip_accents":
            result = _strip_accents(result)
        elif step == "strip_punctuation":
            result = result.translate(_PUNCT_TABLE)
        elif step == "strip_legal_suffix":
            result = _strip_legal_suffix(result)
        elif step == "strip_leading_zeros":
            result = _LEADING_ZEROS.sub("", result)
        elif step in ("iso_date", "parse_to_iso_8601"):
            result = _iso_date(result)
        elif step == "strip_ordinal_suffix":
            # _iso_date already strips ordinals internally regardless of step order (see
            # its docstring comment); applying it again here is an idempotent no-op on an
            # already-ordinal-free string. Needed as its own step for a rubric that lists
            # it before iso_date/parse_to_iso_8601 (as docs/rubric.md's DATE rule does),
            # or that applies it to a non-date field.
            result = _strip_ordinal_suffix(result)
        elif step == "ampersand_to_and":
            result = _ampersand_to_and(result)
        elif step == "expand_two_digit_year_using_document_context":
            # Genuinely resolving an ambiguous two-digit year needs the surrounding
            # document text, which this function's signature (value, steps -> str) has
            # no access to -- threading document context through the grading pipeline
            # is a real architecture change, out of scope here. But docs/rubric.md
            # declares this step AFTER parse_to_iso_8601 for DATE, and none of
            # _DATE_FORMATS or _SLASH_DATE accept a two-digit year -- so by the time
            # this step is reached, `result` is already a fully-resolved 4-digit-year
            # ISO date (any genuinely ambiguous 2-digit-year value would already have
            # raised "unparseable date" at the parse_to_iso_8601 step, never reaching
            # here). This is therefore a no-op on an already-resolved date -- nothing
            # left to expand -- and raises only if it is ever reached without one
            # (a rubric that declared it first, or a non-ISO value), which no current
            # data does: generate.py (Task 8) always emits 4-digit years.
            if not _RESOLVED_ISO_DATE.match(result):
                raise ValueError(
                    "expand_two_digit_year_using_document_context: cannot resolve a "
                    "two-digit year without the surrounding document, which this "
                    "grader does not have access to"
                )
        else:
            raise UnknownNormalisationStep(f"unknown normalisation step: {step!r}")
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
