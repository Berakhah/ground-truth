"""Pytest configuration."""

import os
import sys
from pathlib import Path

import pytest

# Add the project root to sys.path so tests can import from ground_truth
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


def require_or_skip(prerequisite_met: bool, reason: str) -> None:
    """Skip a release-gating test unless its prerequisite is met -- except under
    GT_REQUIRE_DB=1, where a missing prerequisite is a hard failure instead.

    2026-08-29 audit finding 7: publish.yml made test_reproducibility.py and
    test_contamination.py "blocking", but both silently skip without data/results.duckdb --
    which a fresh checkout always lacks, since data/*.duckdb is gitignored. A skipped test is
    a green tick with nothing behind it. publish.yml sets GT_REQUIRE_DB=1 so these tests
    actually gate a release; a bare `pytest` locally still skips.
    """
    if prerequisite_met:
        return
    if os.environ.get("GT_REQUIRE_DB"):
        pytest.fail(reason)
    pytest.skip(reason)


def require_sweep_data(con, reason: str = "run the sweep first") -> None:
    """Skip (or fail under GT_REQUIRE_DB=1) unless `con` has real sweep output rows.

    `data/results.duckdb` existing is not evidence a sweep ran: `ground_truth.golden.build`
    connects to that same path and migrates its schema while building the synthetic item
    set alone, leaving `outputs`/`runs`/`judge_samples`/`verdicts` empty. A fixture that
    gates only on `DB.exists()` then either fails confusingly (a test asserting the data
    varies, against zero rows) or passes vacuously (a test asserting an empty set contains
    nothing) -- the same "a test a placeholder passes is not a control" failure mode the
    2026-08-29 audit caught for `artifacts/`, here for the DB path instead. Closes `con`
    before skipping so a skip doesn't leak an open handle into the next fixture.
    """
    has_data = con.execute("SELECT count(*) FROM outputs").fetchone()[0] > 0
    if not has_data:
        con.close()
    require_or_skip(has_data, reason)
