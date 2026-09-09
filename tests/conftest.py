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
