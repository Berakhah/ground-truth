"""Cut a release: stage one of the two-stage release gate.

The reproducibility and contamination gates need `data/results.duckdb`, which is gitignored
because it carries private-split items and model outputs; a CI runner never has it, and
shipping it there would move private data off the machine that holds it. So those gates run
here, where the release is cut, and only if they pass is `release.json` written: the sha256 of
every artifact they saw. The release job (.github/workflows/publish.yml) then runs
`scripts/reproduce.py --require-release`, which needs no database: it refuses any file the
gates did not see or that changed since, and recomputes every headline from the published
verdicts.

The attestation records that the gates ran here; it cannot prove it. What a stranger can
check without trusting us is the recomputation.

    uv run python -m ground_truth.publish.release --as-of 2026-10-15T00:00:00+00:00 \
        --analysis-seed 1
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ground_truth.artifact_names import RELEASE
from ground_truth.publish.artifacts import emit_all, write_json
from ground_truth.store.db import connect

REPO = Path(__file__).resolve().parents[2]
# The gate tests read these fixed paths, so a release is cut only from them.
DB = REPO / "data" / "results.duckdb"
ARTIFACTS = REPO / "artifacts"
_DEFAULT_MODELS_YAML = REPO / "models.yaml"
GATES = ("tests/test_reproducibility.py", "tests/test_contamination.py")


class GatesFailed(RuntimeError):
    """The DB-backed gates did not pass; no attestation was written."""


def write_attestation(
    out_dir: Path, *, as_of: datetime, analysis_seed: int, gates: list[str]
) -> Path:
    # Only files are hashed, so a directory would be committed and tagged unseen (security
    # review 2026-09-29). Nothing here writes one; refuse rather than attest around it.
    folders = sorted(p.name for p in out_dir.iterdir() if not p.is_file())
    if folders:
        raise ValueError(f"refusing to attest {out_dir}: it holds non-files {folders}")
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out_dir.iterdir())
        if p.is_file() and p.name != RELEASE
    }
    path = out_dir / RELEASE
    write_json(
        path,
        {
            "as_of": as_of.isoformat(),
            "analysis_seed": analysis_seed,
            "gates": list(gates),
            "files": files,
        },
    )
    return path


def run_db_gates() -> bool:
    """GT_REQUIRE_DB=1 turns the gates' local skip into a failure (2026-08-29 audit, finding
    7): a skipped gate is a green tick with nothing behind it."""
    env = {**os.environ, "GT_REQUIRE_DB": "1"}
    command = [sys.executable, "-m", "pytest", *GATES, "-v"]
    result = subprocess.run(command, cwd=REPO, env=env, check=False)  # noqa: S603
    return result.returncode == 0


def cut_release(  # noqa: PLR0913 -- run_gates is injected so the gate outcome is testable
    db: Path,
    out_dir: Path,
    *,
    as_of: datetime,
    analysis_seed: int,
    models_yaml: Path = _DEFAULT_MODELS_YAML,
    run_gates: Callable[[], bool] = run_db_gates,
) -> Path:
    con = connect(db)
    try:
        emit_all(con, out_dir, as_of=as_of, analysis_seed=analysis_seed, models_yaml=models_yaml)
    finally:
        con.close()
    if not run_gates():
        raise GatesFailed(
            f"the release gates failed; {out_dir} holds unattested artifacts that CI will refuse"
        )
    return write_attestation(out_dir, as_of=as_of, analysis_seed=analysis_seed, gates=list(GATES))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit the artifacts, run the DB-backed release gates, and attest them."
    )
    parser.add_argument(
        "--as-of",
        type=datetime.fromisoformat,
        required=True,
        help="ISO 8601 release timestamp stamped into the artifacts -- never `now`",
    )
    parser.add_argument("--analysis-seed", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        path = cut_release(DB, ARTIFACTS, as_of=args.as_of, analysis_seed=args.analysis_seed)
    except GatesFailed as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"attested {path}; commit artifacts/ and tag the release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
