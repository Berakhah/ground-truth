"""File names in the published `artifacts/` folder that more than one module needs to agree on.

A plain constants module, so `publish.artifacts` can name another emitter's file without
importing that emitter (and, for the triage example, without importing `triage/` at all).
"""

from __future__ import annotations

# Written by `triage.export_example` from the synthetic intake in docs/triage-example.csv.
TRIAGE_EXAMPLE = "triage_example.json"
# Written by the regression sweep, which runs locally; its redacted result is committed by hand
# (.github/workflows/regression-watch.yml). `emit_all` writes an empty stub only when none is
# committed.
REGRESSION = "regression.json"
# Written by `publish.release` only after the DB-backed release gates pass: the sha256 of every
# artifact they saw. `emit_all` drops it (a re-emit is bytes the gates have not seen), and
# scripts/reproduce.py --require-release checks it in CI, which never holds the database.
RELEASE = "release.json"
