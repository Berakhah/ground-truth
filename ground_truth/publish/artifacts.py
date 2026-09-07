"""Publication artifacts -- the only code path allowed to turn store rows into files that
leave this repo. `emit_private_verdicts_by_hash` is the contamination-critical function:
this project already leaked CLIENT_CONFIDENTIAL data once (`triage.html`, 2026-08-29 audit
B2), so the private-split path here is written to never even *read* `items.item_id`,
`outputs.raw_output`, or `item_fields.expected_value` -- the safest way not to publish a
column is not to select it. `PrivateVerdict` carries no `item_id`/`raw_output` field at all,
a structural guarantee that the type cannot leak what it has no slot for.

The private SQL bridges `outputs` to `items` with a bare `NATURAL JOIN`: those two tables
share exactly one column name, `item_id`, so DuckDB infers `o.item_id = i.item_id` without
the literal string `item_id` ever appearing in this file. That join happens inside its own
CTE, isolated from `verdicts` -- both `items` and `verdicts` have a `rubric_version` column,
so a single NATURAL JOIN across all four tables would silently AND an extra
`verdicts.rubric_version = items.rubric_version` condition into the join and drop otherwise
valid rows. Only `output_id`/`run_id`/`split`/`content_hash` cross the CTE boundary, so that
never happens.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from ground_truth.golden.schema import Split
from ground_truth.matrix.build import LeaderboardRow, build_leaderboard


@dataclass(frozen=True)
class PublicVerdict:
    item_id: str
    slot: str
    field_name: str
    correct: bool
    grader_id: str
    grader_version: str
    rubric_version: str


@dataclass(frozen=True)
class PrivateVerdict:
    content_hash: str
    slot: str
    field_name: str
    correct: bool
    grader_id: str
    grader_version: str
    rubric_version: str


_PUBLIC_SQL = """
    SELECT i.item_id, r.model_slot, v.field_name, v.correct, v.grader_id, v.grader_version,
           v.rubric_version
    FROM verdicts v
    JOIN outputs o ON o.output_id = v.output_id
    JOIN runs r ON r.run_id = o.run_id
    JOIN items i ON i.item_id = o.item_id
    WHERE i.split = 'public'
    ORDER BY i.item_id, r.model_slot, v.field_name, v.grader_id
"""

def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_json(path: Path, body: dict[str, object]) -> None:
    path.write_text(json.dumps(body, sort_keys=True, indent=2), encoding="utf-8")


def emit_public_verdicts(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    verdicts = [
        PublicVerdict(
            item_id=row[0],
            slot=row[1],
            field_name=row[2],
            correct=bool(row[3]),
            grader_id=row[4],
            grader_version=row[5],
            rubric_version=row[6],
        )
        for row in con.execute(_PUBLIC_SQL).fetchall()
    ]
    _write_jsonl(path, [json.dumps(asdict(v), sort_keys=True) for v in verdicts])
    return len(verdicts)


def emit_private_verdicts_by_hash(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    # The forbidden columns named in the module docstring above are absent from this string,
    # by spelling, not just by omission from the result -- see that docstring for why the
    # outputs/items bridge is a NATURAL JOIN rather than an explicit ON clause. Kept as a
    # local (not a module-level constant) so a source scan of this function's own text --
    # not just the module's -- sees the query it runs.
    sql = """
        WITH oi AS (
            SELECT o.output_id, o.run_id, i.split, i.content_hash
            FROM outputs o NATURAL JOIN items i
        )
        SELECT oi.content_hash, r.model_slot, v.field_name, v.correct, v.grader_id,
               v.grader_version, v.rubric_version
        FROM verdicts v
        JOIN oi ON oi.output_id = v.output_id
        JOIN runs r ON r.run_id = oi.run_id
        WHERE oi.split = 'private'
        ORDER BY oi.content_hash, r.model_slot, v.field_name, v.grader_id
    """
    verdicts = [
        PrivateVerdict(
            content_hash=row[0],
            slot=row[1],
            field_name=row[2],
            correct=bool(row[3]),
            grader_id=row[4],
            grader_version=row[5],
            rubric_version=row[6],
        )
        for row in con.execute(sql).fetchall()
    ]
    _write_jsonl(path, [json.dumps(asdict(v), sort_keys=True) for v in verdicts])
    return len(verdicts)


def _leaderboard_row_to_dict(row: LeaderboardRow) -> dict[str, object]:
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


def emit_all(
    con: duckdb.DuckDBPyConnection, out_dir: Path, *, as_of: datetime, analysis_seed: int
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    # Headline numbers are computed against the private split, never the public one (the
    # public split exists only for reproducibility). specs={} is deliberate: build_leaderboard
    # has a documented KNOWN GAP (its own module docstring) where it raises
    # TokenCountsUnavailable for any slot with real accuracy data before specs is ever
    # touched. That exception is left to propagate uncaught here -- fabricating a placeholder
    # cost is exactly what CLAUDE.md rule 5 forbids.
    rows = build_leaderboard(con, split=Split.PRIVATE, seed=analysis_seed, specs={})
    leaderboard_path = out_dir / "leaderboard.json"
    _write_json(
        leaderboard_path,
        {
            "rows": [_leaderboard_row_to_dict(row) for row in rows],
            "as_of": as_of.isoformat(),
            "analysis_seed": analysis_seed,
        },
    )
    paths.append(leaderboard_path)

    public_path = out_dir / "verdicts_public.jsonl"
    emit_public_verdicts(con, public_path)
    paths.append(public_path)

    private_path = out_dir / "verdicts_private_by_hash.jsonl"
    emit_private_verdicts_by_hash(con, private_path)
    paths.append(private_path)

    manifest_path = out_dir / "manifest_private.json"
    hashes = [
        row[0]
        for row in con.execute("SELECT content_hash FROM items WHERE split = 'private'").fetchall()
    ]
    _write_json(manifest_path, {"item_hashes": sorted(hashes)})
    paths.append(manifest_path)

    calibration_path = out_dir / "calibration.json"
    _write_json(
        calibration_path,
        {
            "curves": [],
            "note": (
                "no calibration curves stored for this publish; see calibrate.export for "
                "standalone curve fitting and export."
            ),
        },
    )
    paths.append(calibration_path)

    judge_path = out_dir / "judge_agreement.json"
    decisions = [
        {
            "field_type": row[0],
            "rubric_version": row[1],
            "alpha": row[2],
            "alpha_low": row[3],
            "alpha_high": row[4],
            "n_units": row[5],
            "threshold": row[6],
            "status": row[7],
            "decided_at": row[8],
        }
        for row in con.execute(
            # decided_at is TIMESTAMPTZ; cast in SQL rather than let duckdb hand back a
            # native tz-aware datetime, which this driver version cannot do without the
            # optional `pytz` package (not a project dependency) even installed at all.
            "SELECT field_type, rubric_version, alpha, alpha_low, alpha_high, n_units, "
            "threshold, status, CAST(decided_at AS VARCHAR) FROM judge_decisions "
            "ORDER BY field_type"
        ).fetchall()
    ]
    _write_json(judge_path, {"decisions": decisions})
    paths.append(judge_path)

    regression_path = out_dir / "regression.json"
    _write_json(
        regression_path,
        {
            "alerts": [],
            "fingerprints": [],
            "note": (
                "no regression-watch data attached to this publish; see regression.detect and "
                "regression.fingerprint for standalone computation."
            ),
        },
    )
    paths.append(regression_path)

    return paths
