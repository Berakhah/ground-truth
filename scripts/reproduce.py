#!/usr/bin/env python3
"""Recompute the published headline accuracy numbers from published data alone.

Standalone, stdlib-only: this script deliberately does NOT import `ground_truth` (or any
third-party package). If reproducing the published numbers required our package, it would not
be reproduction -- CLAUDE.md's brand claim is "a number you can reproduce," and the intended
reader is a stranger with no repository checkout and no `ground_truth` installed.

Usage:
    python reproduce.py <artifacts-dir>

Reads two files from <artifacts-dir>:
  - leaderboard.json               -- published headline accuracy per slot (`rows[].accuracy.point`)
  - verdicts_private_by_hash.jsonl -- one JSON object per line: content_hash, slot, correct, ...

For each leaderboard row, recomputes headline accuracy as the mean, across all private-split
content hashes graded under that slot, of each hash's own mean correctness across its verdict
rows (mean-of-per-item-means, not a flat mean over all rows -- an item with more graded fields
must not outweigh one with fewer). This is exactly the arithmetic in
`tests/test_reproducibility.py::test_headline_accuracy_recomputes_from_published_verdicts_alone`.

Exits 0 if every slot's recomputed accuracy matches the published point estimate within
TOLERANCE, non-zero otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Matches the test's `pytest.approx(..., abs=1e-9)` -- both recompute the identical
# mean-of-means arithmetic in Python's own float type, so no printing/serialization error
# can creep in and a mismatch above float noise means the published number is genuinely wrong.
TOLERANCE = 1e-9

_EXPECTED_ARGC = 2  # program name + artifacts-dir


def recompute_accuracy(verdicts: list[dict[str, object]], slot: str) -> float:
    by_hash: dict[str, list[bool]] = {}
    for v in verdicts:
        if v["slot"] == slot:
            by_hash.setdefault(str(v["content_hash"]), []).append(bool(v["correct"]))
    if not by_hash:
        raise ValueError(f"no private verdicts found for slot {slot!r}")
    return sum(sum(c) / len(c) for c in by_hash.values()) / len(by_hash)


def main(argv: list[str]) -> int:
    if len(argv) != _EXPECTED_ARGC:
        print(f"usage: {argv[0]} <artifacts-dir>", file=sys.stderr)
        return 2

    artifacts_dir = Path(argv[1])
    leaderboard = json.loads((artifacts_dir / "leaderboard.json").read_text(encoding="utf-8"))
    verdicts = [
        json.loads(line)
        for line in (artifacts_dir / "verdicts_private_by_hash.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]

    header = f"{'slot':<30} {'published':>12} {'recomputed':>12} {'diff':>12}"
    print(header)
    print("-" * len(header))

    mismatches: list[str] = []
    for entry in leaderboard["rows"]:
        slot = entry["slot"]
        published = entry["accuracy"]["point"]
        recomputed = recompute_accuracy(verdicts, slot)
        diff = recomputed - published
        print(f"{slot:<30} {published:>12.9f} {recomputed:>12.9f} {diff:>12.2e}")
        if abs(diff) > TOLERANCE:
            mismatches.append(slot)

    print()
    if mismatches:
        print(f"MISMATCH: {len(mismatches)} slot(s) do not reproduce: {mismatches}")
        return 1

    print(f"OK: all {len(leaderboard['rows'])} slot(s) reproduce within {TOLERANCE:g}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
