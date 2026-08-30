from __future__ import annotations

import json
import re

from ground_truth.golden.schema import Item
from ground_truth.graders.base import Verdict

GRADER_ID = "schema"
GRADER_VERSION = "1"

# A leading/trailing markdown code fence, with or without a "json" language tag, wrapped
# around the whole payload. DOTALL so the captured body may itself span lines.
_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def extract_fields(raw_output: str) -> dict[str, str]:
    text = raw_output.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"invalid json: expected an object, got {type(parsed).__name__}")
    return parsed


def grade_schema(item: Item, raw_output: str) -> Verdict:
    def verdict(correct: bool, reason: str) -> Verdict:
        return Verdict(
            correct=correct, reason=reason, grader_id=GRADER_ID, grader_version=GRADER_VERSION
        )

    try:
        parsed = extract_fields(raw_output)
    except ValueError as exc:
        return verdict(False, str(exc))

    expected_keys = {f.field_name for f in item.fields}
    actual_keys = set(parsed.keys())
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing fields: {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"extra fields: {', '.join(sorted(extra))}")
        return verdict(False, "; ".join(parts))

    non_string = sorted(key for key, value in parsed.items() if not isinstance(value, str))
    if non_string:
        return verdict(False, f"non-string values for fields: {', '.join(non_string)}")

    return verdict(True, "schema valid")
