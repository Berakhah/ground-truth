#!/usr/bin/env python3
"""Recompute the published headline accuracy numbers from published data alone.

Standalone, stdlib-only: this script deliberately does NOT import `ground_truth` (or any
third-party package). If reproducing the published numbers required our package, it would not
be reproduction -- CLAUDE.md's brand claim is "a number you can reproduce," and the intended
reader is a stranger with no repository checkout and no `ground_truth` installed.

Usage:
    python reproduce.py <artifacts-dir> [--require-release]

Reads two files from <artifacts-dir>:
  - leaderboard.json               -- published headline accuracy per slot (`rows[].accuracy.point`)
  - verdicts_private_by_hash.jsonl -- one JSON object per line: content_hash, slot, correct,
                                      counts_toward_headline, weight, ...

For each leaderboard row, recomputes headline accuracy as the mean, across all private-split
content hashes graded under that slot, of each hash's own weighted mean correctness across its
verdict rows flagged `counts_toward_headline`, each row counted `weight` times (the file also
lists verdicts the headline does not count, with the flag false; a file without the flag
counts every row, and a row without `weight` counts once)
(mean-of-per-item-means, not a flat mean over all rows -- an item with more graded fields
must not outweigh one with fewer). This is exactly the arithmetic in
`tests/test_reproducibility.py::test_headline_accuracy_recomputes_from_published_verdicts_alone`.

Exits 0 if every slot's recomputed accuracy matches the published point estimate within
TOLERANCE, non-zero otherwise. Placeholder/demo data (any artifact flagged `"placeholder":
true`) and an empty leaderboard are refused: "reproducing" either proves nothing.

--require-release (the release job's gate, .github/workflows/publish.yml): also requires
`release.json`, written by `ground_truth.publish.release` only after the DB-backed
reproducibility and contamination gates passed on the machine that cut the release -- CI never
holds the results database, which carries private-split outputs. Every file in <artifacts-dir>
must be listed there with the sha256 the gates saw, and its as_of and analysis_seed must be the
leaderboard's. An attestation records that the gates ran; it is not proof they did. The proof a
stranger can check is the recomputation above.

SECURITY (00 security baseline, Task 52): this is the one script strangers are invited to
download and run against untrusted, attacker-controllable input -- a downloaded `artifacts/`
directory nobody here signs or vets before a reader fetches it. It parses that input with
`json.loads` only, and must NEVER be changed to use `eval`, `exec`, `pickle`, or `yaml.load`
(even with a "trusted" default `Loader=` -- use `yaml.safe_load` if YAML is ever needed here),
all of which can execute arbitrary code from file content alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Matches the test's `pytest.approx(..., abs=1e-9)` -- both recompute the identical
# mean-of-means arithmetic in Python's own float type, so no printing/serialization error
# can creep in and a mismatch above float noise means the published number is genuinely wrong.
TOLERANCE = 1e-9

RELEASE = "release.json"  # ground_truth/artifact_names.py; this script imports nothing of ours


def recompute_accuracy(verdicts: list[dict[str, object]], slot: str) -> float:
    by_hash: dict[str, list[tuple[bool, int]]] = {}
    for v in verdicts:
        # The file also lists verdicts the headline does not count (schema checks, judges
        # without an accepted decision, a judge no longer assigned, retired items); each says so
        # in `counts_toward_headline`. `weight` is how many times a counted verdict counts: 1
        # for a deterministic verdict (one per replicate), the replicate count of its (item,
        # slot) for a judge verdict (one per item and slot). A release published before these
        # fields lacks them, and then every row counts once, as this script always assumed.
        if v["slot"] == slot and v.get("counts_toward_headline", True) is True:
            weight = v.get("weight", 1)
            if not isinstance(weight, int) or isinstance(weight, bool) or weight < 1:
                raise ValueError(f"a counted verdict has an invalid weight: {weight!r}")
            by_hash.setdefault(str(v["content_hash"]), []).append((bool(v["correct"]), weight))
    if not by_hash:
        raise ValueError(f"no private verdicts found for slot {slot!r}")
    return sum(
        sum(w for c, w in rows if c) / sum(w for _, w in rows) for rows in by_hash.values()
    ) / len(by_hash)


def placeholder_files(artifacts_dir: Path) -> list[str]:
    return sorted(
        p.name
        for p in artifacts_dir.glob("*.json")
        if isinstance(doc := json.loads(p.read_text(encoding="utf-8")), dict)
        and doc.get("placeholder") is True
    )


def release_problems(artifacts_dir: Path, leaderboard: dict[str, object]) -> list[str]:
    """Why these files are not the ones the release gates passed; empty if they are."""
    path = artifacts_dir / RELEASE
    if not path.is_file():
        return [f"no {RELEASE}: these artifacts were not cut through the release gates"]
    attestation = json.loads(path.read_text(encoding="utf-8"))
    problems = [
        f"{RELEASE} has {key}={attestation.get(key)!r}, "
        f"leaderboard.json has {leaderboard.get(key)!r}"
        for key in ("as_of", "analysis_seed")
        if attestation.get(key) != leaderboard.get(key)
    ]
    attested: dict[str, str] = attestation.get("files", {})
    entries = list(artifacts_dir.iterdir())
    problems += [
        f"{p.name} is not a file; the release gates see only files"
        for p in sorted(entries)
        if not p.is_file()
    ]
    present = {p.name for p in entries if p.is_file() and p.name != RELEASE}
    problems += [f"{name} is attested but missing" for name in sorted(set(attested) - present)]
    problems += [
        f"{name} was never seen by the release gates" for name in sorted(present - set(attested))
    ]
    problems += [
        f"{name} changed after the release gates passed"
        for name in sorted(present & set(attested))
        if hashlib.sha256((artifacts_dir / name).read_bytes()).hexdigest() != attested[name]
    ]
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=Path(argv[0]).name)
    parser.add_argument("artifacts_dir", type=Path)
    parser.add_argument("--require-release", action="store_true")
    args = parser.parse_args(argv[1:])

    artifacts_dir: Path = args.artifacts_dir
    placeholders = placeholder_files(artifacts_dir)
    if placeholders:
        print(f"REFUSED: placeholder/demo data, not a release: {placeholders}")
        return 1
    leaderboard = json.loads((artifacts_dir / "leaderboard.json").read_text(encoding="utf-8"))
    if not leaderboard.get("rows"):
        print("REFUSED: leaderboard.json has no rows; there is nothing to reproduce.")
        return 1
    if args.require_release:
        problems = release_problems(artifacts_dir, leaderboard)
        if problems:
            print("REFUSED: not the artifacts the release gates passed:")
            for problem in problems:
                print(f"  - {problem}")
            return 1

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
