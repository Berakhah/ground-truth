from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import duckdb


def freeze_plan(con: duckdb.DuckDBPyConnection, path: Path, version: str) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    row = con.execute(
        "SELECT content_hash FROM analysis_plan WHERE plan_version = ?", [version]
    ).fetchone()
    if row is not None:
        if row[0] != digest:
            raise ValueError(f"analysis plan {version} is already frozen with a different hash")
        return digest
    con.execute("INSERT INTO analysis_plan VALUES (?, ?, ?)", [version, digest, datetime.now(UTC)])
    return digest


def assert_frozen_before_first_sweep(con: duckdb.DuckDBPyConnection) -> None:
    frozen_row = con.execute("SELECT min(frozen_at) FROM analysis_plan").fetchone()
    first_run_row = con.execute("SELECT min(started_at) FROM runs").fetchone()
    # SELECT min(...) always returns exactly one row, even on an empty table (as NULL);
    # the assertion documents that invariant for mypy's benefit, it never fires.
    assert frozen_row is not None and first_run_row is not None
    frozen = frozen_row[0]
    first_run = first_run_row[0]
    if first_run is None:
        return
    assert frozen is not None, "pre-registration missing: no analysis plan is frozen"
    assert frozen < first_run, (
        f"pre-registration violated: plan frozen {frozen} but a sweep started {first_run}"
    )
