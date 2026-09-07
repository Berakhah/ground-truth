"""The published leaderboard payload -- the headline artifact.

Every row's `accuracy` always serialises the full `Interval` (point/low/high/n/method):
there is no code path that emits a bare point estimate. That is CLAUDE.md rule 2, "no claim
without its sample," made structural rather than editorial.

`required_terms`/`assert_methodology_defines_every_term` make DoD item 11 ("a published
definition for every term used") executable: the published vocabulary is listed once here,
and CI (via `tests/publish/test_leaderboard.py`) fails if `docs/methodology.md` stops
defining any of it.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ground_truth.graders.judge.agreement import AgreementReport
    from ground_truth.matrix.build import LeaderboardRow
    from ground_truth.regression.fingerprint import SlotFingerprint

METHODOLOGY_URL = "/methodology"

_REQUIRED_TERMS = frozenset(
    {
        "accurate",
        "correct",
        "field",
        "item",
        "replicate",
        "split",
        "public split",
        "private split",
        "verdict",
        "grader",
        "judge",
        "interval",
        "list price",
        "not distinguishable",
        "minimum detectable effect",
        "look",
        "rubric",
    }
)

# Matches a Markdown definition line: "**term**" or "- **term**" at the start of the line
# (after optional leading whitespace), case-sensitive on the term text itself.
_DEFINITION_LINE = re.compile(r"^\s*(?:-\s*)?\*\*(?P<term>[^*]+)\*\*")


def required_terms() -> set[str]:
    return set(_REQUIRED_TERMS)


def _row_to_dict(row: LeaderboardRow) -> dict[str, object]:
    return {
        "slot": row.slot,
        "accuracy": row.accuracy.model_dump(),
        "cost": {
            "value": str(row.cost.value),
            "unit": row.cost.unit,
            "method": row.cost.method,
            "source_url": row.cost.source_url,
            "retrieved_at": row.cost.retrieved_at.isoformat(),
            "caveat": row.cost.caveat,
        },
        "latency": asdict(row.latency),
        "per_field": {name: interval.model_dump() for name, interval in row.per_field.items()},
    }


def _agreement_to_dict(report: AgreementReport) -> dict[str, object]:
    return {
        "field_type": report.field_type,
        "alpha": report.alpha,
        "alpha_ci": report.alpha_ci.model_dump(),
        "status": report.status.value,
        "n_units": report.n_units,
        "statement": report.statement,
    }


def _fingerprint_to_dict(fingerprint: SlotFingerprint) -> dict[str, object]:
    return {
        "slot": fingerprint.slot,
        "status": fingerprint.status.value,
        "values": fingerprint.values,
        "first_seen": fingerprint.first_seen.isoformat(),
        "last_seen": fingerprint.last_seen.isoformat(),
        "statement": fingerprint.statement,
    }


def leaderboard_payload(  # noqa: PLR0913 -- fixed public interface, brief's exact signature
    rows: list[LeaderboardRow],
    statements: list[str],
    agreements: list[AgreementReport],
    fingerprints: list[SlotFingerprint],
    *,
    as_of: datetime,
    version: str,
) -> dict[str, object]:
    return {
        "version": version,
        "as_of": as_of.isoformat(),
        "methodology_url": METHODOLOGY_URL,
        "rows": [_row_to_dict(row) for row in rows],
        "distinguishability": list(statements),
        "judge_agreement": [_agreement_to_dict(report) for report in agreements],
        "fingerprints": [_fingerprint_to_dict(fp) for fp in fingerprints],
        # No MDE calculation is wired into this payload's inputs (see this function's exact
        # signature) -- an honest "not measured" note, not a silent bare [], matching the
        # empty-state convention `publish.artifacts.emit_all` already uses for calibration
        # and regression sections.
        "mde": {
            "statements": [],
            "note": (
                "no minimum-detectable-effect calculation attached to this payload; see "
                "ground_truth.stats.mde.describe_mde for standalone computation."
            ),
        },
    }


def write_leaderboard(payload: dict[str, object], path: Path) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")


def assert_methodology_defines_every_term(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    defined = {
        match.group("term").strip().lower()
        for line in text.splitlines()
        if (match := _DEFINITION_LINE.match(line))
    }
    missing = {term for term in _REQUIRED_TERMS if term.lower() not in defined}
    if missing:
        raise AssertionError(
            f"docs/methodology.md is missing a definition for: {sorted(missing)}"
        )
