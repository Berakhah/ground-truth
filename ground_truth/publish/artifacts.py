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

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from ground_truth.artifact_names import REGRESSION, RELEASE, TRIAGE_EXAMPLE
from ground_truth.golden.manifest import write_manifest_from_db
from ground_truth.golden.schema import Split
from ground_truth.matrix.build import LeaderboardRow, build_leaderboard
from ground_truth.providers import load_slots
from ground_truth.store.db import connect

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_MODELS_YAML = _REPO / "models.yaml"


@dataclass(frozen=True)
class PublicVerdict:
    item_id: str
    slot: str
    field_name: str
    correct: bool
    grader_id: str
    grader_version: str
    rubric_version: str
    reason: str


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
           v.rubric_version, v.reason
    FROM verdicts v
    JOIN outputs o ON o.output_id = v.output_id
    JOIN runs r ON r.run_id = o.run_id
    JOIN items i ON i.item_id = o.item_id
    WHERE i.split = 'public'
    ORDER BY i.item_id, r.model_slot, v.field_name, v.grader_id
"""


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_json(path: Path, body: dict[str, object]) -> None:
    # allow_nan=False: the default writes NaN as a bare `NaN` token, which is not JSON. A
    # non-finite value must be mapped to null by `finite_or_none` at the call site, where the
    # reason it is undefined is known, or this raises rather than publish a broken file.
    path.write_text(json.dumps(body, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")


def finite_or_none(value: object) -> object:
    """Map a non-finite float (an undefined judge alpha -- `agreement._undefined_alpha_report`)
    to None, so it publishes as JSON null next to the statement that says why."""
    return None if isinstance(value, float) and not math.isfinite(value) else value


def _judge_decision(row: tuple[object, ...]) -> dict[str, object]:
    """One `judge_decisions` row as published, with the statement and interval method `assess`
    stored. The publisher never writes its own reason: an earlier version rebuilt "every unit
    got the same verdict" from a NaN alpha, which any future path to a NaN would have published
    as a false reason (stats code review 2026-09-27 #2, finding 6)."""
    decision: dict[str, object] = {
        "field_type": row[0],
        "rubric_version": row[1],
        "alpha": finite_or_none(row[2]),
        "alpha_low": finite_or_none(row[3]),
        "alpha_high": finite_or_none(row[4]),
        "n_units": row[5],
        "threshold": row[6],
        "status": row[7],
        "decided_at": row[8],
        "statement": row[9],
        "alpha_method": row[10],
    }
    if decision["statement"] is None and decision["alpha"] is None:
        # Recorded before `statement` was stored: the value is undefined and the reason is not
        # known, so say exactly that rather than guess one.
        decision["statement"] = (
            f"Krippendorff's alpha is undefined, n={row[5]}; the reason was not recorded with "
            f"this decision. Treated as below the threshold of {row[6]}; this field type is not "
            "used for headline scoring and is reported as not measured."
        )
    return decision


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
            reason=row[7],
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


def leaderboard_row_to_dict(row: LeaderboardRow) -> dict[str, object]:
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
    con: duckdb.DuckDBPyConnection,
    out_dir: Path,
    *,
    as_of: datetime,
    analysis_seed: int,
    models_yaml: Path = _DEFAULT_MODELS_YAML,
) -> list[Path]:
    """Write every artifact into a staging directory beside `out_dir`, then swap it in whole.

    `write_json` refuses a non-finite value, and before staging that refusal landed mid-way
    through the writes: the files already written stayed in `out_dir` beside the previous
    release's, a mixed publish the reproducibility check then reads (stats code review
    2026-09-27 #2, finding 9). Moving staged files in one at a time kept the same failure one
    step later -- a move failing partway, as it does on Windows when a dev server or antivirus
    holds a file open, left the folder mixed (code review 2026-09-28 #4). Now a failure at any
    point leaves `out_dir` exactly as it was.
    """
    # Before the analysis: the emitted names are static, so a refusal needs only a listing.
    _refuse_unrecognised(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}-staging-", dir=out_dir.parent))
    try:
        staged = _emit_into(
            con, staging, as_of=as_of, analysis_seed=analysis_seed, models_yaml=models_yaml
        )
        _carry_over(out_dir, staging)
        _swap_in(staging, out_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return [out_dir / path.relative_to(staging) for path in staged]


# Every name `_emit_into` writes; a test keeps this in step with what it actually writes.
EMITTED = (
    "leaderboard.json",
    "verdicts_public.jsonl",
    "verdicts_private_by_hash.jsonl",
    "manifest_private.json",
    "calibration.json",
    "judge_agreement.json",
    REGRESSION,
)

# Carried across the swap when present as a file. The triage example and a committed
# regression-watch result are written by other emitters (a committed regression.json replaces
# `_emit_into`'s empty stub -- overwriting it wiped real findings, re-review 2026-09-28, since
# 5ada687); the rest is folder metadata that must neither block a publish nor be lost.
_CARRIED = (TRIAGE_EXAMPLE, REGRESSION, ".gitkeep", ".DS_Store", "Thumbs.db", "desktop.ini")


# Accepted in `out_dir` but deliberately not carried, so the swap drops it: the release
# attestation vouches for the bytes the release gates saw, which a re-emit replaces.
_DROPPED = (RELEASE,)


def _dropped(entry: Path) -> bool:
    return entry.name in _DROPPED and entry.is_file()


def _carried(entry: Path) -> bool:
    # One predicate for the refusal and the copy: a directory under a carried name passed the
    # check, was not copied, and the swap deleted it.
    return entry.name in _CARRIED and entry.is_file()


def _refuse_unrecognised(out_dir: Path) -> None:
    """Raise, before anything changes, if `out_dir` holds entries this publish neither writes
    nor carries over. The swap replaces the whole folder, so such an entry would otherwise be
    republished (a stray triage output: the 2026-08-29 leak class) or deleted (`--out data`
    would take results.duckdb with it). Refusing neither leaks nor loses anything
    (re-review 2026-09-28)."""
    if not out_dir.exists():
        return
    unrecognised = sorted(
        entry.name
        for entry in out_dir.iterdir()
        if entry.name not in EMITTED and not _dropped(entry) and not _carried(entry)
    )
    if unrecognised:
        raise ValueError(
            f"refusing to publish into {out_dir}: it holds {', '.join(unrecognised)}, which "
            "this publish neither writes nor keeps. Move them out (or choose another --out); an "
            "artifact that is no longer emitted must be deleted in the same change that retires "
            "it. Nothing was changed."
        )


def _carry_over(out_dir: Path, staging: Path) -> None:
    """Copy the carried files from `out_dir` into staging, replacing any stub written there.

    Two publishers writing `out_dir` at the same moment still race, as they did before the
    swap: a file written after this copy is replaced along with the folder.
    """
    if not out_dir.exists():
        return
    for entry in out_dir.iterdir():
        if _carried(entry):
            shutil.copy2(entry, staging / entry.name)


def _swap_in(staging: Path, out_dir: Path) -> None:
    """Two renames with a rollback. Renaming `out_dir` aside is the step a held-open file makes
    fail on Windows, and it fails before anything has changed. `os.replace` cannot move a
    folder onto a non-empty one on Windows, hence aside-then-in rather than one replace."""
    if not out_dir.exists():
        os.replace(staging, out_dir)
        return
    backup = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}-previous-", dir=out_dir.parent))
    backup.rmdir()  # a unique free name; os.replace needs the target absent on Windows
    os.replace(out_dir, backup)
    try:
        os.replace(staging, out_dir)
    except BaseException as swap_error:
        if not staging.exists():
            # The rename completed and the error (an interrupt) arrived after it: `out_dir`
            # holds the new release, and "restoring" the backup would overwrite it.
            shutil.rmtree(backup, ignore_errors=True)
            raise
        try:
            os.replace(backup, out_dir)
        except OSError:
            # The lock that failed the swap can fail the rollback too. `out_dir` is then gone,
            # so say where the previous release is instead of stranding it under a hidden name.
            # A note, not a new exception: the caller still sees the original type.
            swap_error.add_note(
                f"{out_dir} could not be restored; the previous release is intact at {backup} "
                f"-- rename it back to {out_dir.name}"
            )
        raise
    # Best effort: the swap has succeeded. A leftover is gitignored (`.gitignore`), so a
    # stale copy of the previous release cannot be committed beside the real one.
    shutil.rmtree(backup, ignore_errors=True)


def _emit_into(
    con: duckdb.DuckDBPyConnection,
    out_dir: Path,
    *,
    as_of: datetime,
    analysis_seed: int,
    models_yaml: Path,
) -> list[Path]:
    paths: list[Path] = []

    # Headline numbers are computed against the private split, never the public one (the
    # public split exists only for reproducibility). Real specs, loaded from models.yaml:
    # build_leaderboard raises TokenCountsUnavailable for any slot whose outputs carry no
    # token count, and that exception is left to propagate uncaught here -- fabricating a
    # placeholder cost is exactly what CLAUDE.md rule 5 forbids.
    rows = build_leaderboard(
        con, split=Split.PRIVATE, seed=analysis_seed, specs=load_slots(models_yaml)
    )
    leaderboard_path = out_dir / "leaderboard.json"
    write_json(
        leaderboard_path,
        {
            "rows": [leaderboard_row_to_dict(row) for row in rows],
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
    write_manifest_from_db(con, Split.PRIVATE, manifest_path)
    paths.append(manifest_path)

    calibration_path = out_dir / "calibration.json"
    write_json(
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
        _judge_decision(row)
        for row in con.execute(
            # decided_at is TIMESTAMPTZ; cast in SQL rather than let duckdb hand back a
            # native tz-aware datetime, which this driver version cannot do without the
            # optional `pytz` package (not a project dependency) even installed at all.
            # `AT TIME ZONE 'UTC'` normalises to UTC *before* the VARCHAR render, so the
            # string is stable regardless of duckdb's session TimeZone (which otherwise
            # defaults to the host's local OS timezone and is never pinned in this repo) --
            # a bare `CAST(decided_at AS VARCHAR)` renders in session-local time and would
            # make this file byte-different on two machines for the same stored instant
            # (review finding, task-40).
            "SELECT field_type, rubric_version, alpha, alpha_low, alpha_high, n_units, "
            "threshold, status, CAST(decided_at AT TIME ZONE 'UTC' AS VARCHAR), statement, "
            "alpha_method FROM judge_decisions ORDER BY field_type"
        ).fetchall()
    ]
    write_json(judge_path, {"decisions": decisions})
    paths.append(judge_path)

    regression_path = out_dir / "regression.json"
    write_json(
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit publication artifacts (leaderboard, verdicts, calibration, "
        "regression watch, judge agreement) from the results store."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/results.duckdb"),
        help="path to the results DuckDB file (default: data/results.duckdb)",
    )
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    # A release's --as-of must be the release tag's own date, not `now`: the reproducibility
    # test re-runs emit_all later and compares byte-for-byte, so a timestamp that moves with
    # the clock can never regenerate identically.
    parser.add_argument(
        "--as-of",
        type=datetime.fromisoformat,
        required=True,
        help="ISO 8601 timestamp stamped into the published artifacts, e.g. the release "
        "tag's date -- never `now`",
    )
    parser.add_argument(
        "--analysis-seed",
        type=int,
        required=True,
        help="bootstrap/analysis RNG seed, published alongside the results so a stranger "
        "can regenerate them exactly",
    )
    parser.add_argument(
        "--models-yaml",
        type=Path,
        default=_DEFAULT_MODELS_YAML,
        help="path to models.yaml (default: repo root's models.yaml)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    con = connect(args.db)
    try:
        paths = emit_all(
            con,
            args.out,
            as_of=args.as_of,
            analysis_seed=args.analysis_seed,
            models_yaml=args.models_yaml,
        )
    finally:
        con.close()
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
