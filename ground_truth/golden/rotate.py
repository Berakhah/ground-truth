"""Private-split rotation (Task 51).

Spec §5.4 commits to rotating 20% of the private split at each published release. Retired
items are marked (`retired_at`), never deleted -- historical verdicts computed against them
must stay valid even after the item leaves the active split.

Rotation introduces a statistical trap that `ground_truth.regression.detect` must guard
against: comparing release N to release N+1 with 20% of the private items different measures
partly cohort change, not model change. `cohort_intersection` is the tool that closes it --
every cross-release comparison must be restricted to the items present in both releases.

The rotation seed is never published, only its name (`seed_ref`, e.g.
`"GT_PRIVATE_SEED_2027Q1"`, pointing at an `.env` key) -- publishing the seed itself would let
anyone reconstruct the newly-rotated-in private items and defeat the whole mechanism, exactly
as `GT_PRIVATE_SEED`/`GT_HASH_SALT` are withheld for the original build (see
`docs/methodology.md`, "Public/private split and the hash salt").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from ground_truth.golden.build import _ENTROPY_FLOOR
from ground_truth.golden.generate import generate, render_document
from ground_truth.golden.schema import Item, Split


@dataclass(frozen=True)
class RotationRecord:
    release: str
    rotated_at: datetime
    retired_hashes: list[str]
    added_hashes: list[str]
    seed_ref: str


def _write_manifest_from_db(con: duckdb.DuckDBPyConnection, golden_dir: Path) -> None:
    # Deliberately NOT `write_manifest(items, ...)` (ruling 3): that function needs full
    # in-memory `Item` objects (fields, layout), which are not recoverable from DB rows for
    # the items that were already active before this rotation ran. Rewritten directly from
    # the DB instead, in the exact shape `write_manifest` produces.
    rows = con.execute(
        "SELECT content_hash FROM items WHERE split='private' AND retired_at IS NULL "
        "ORDER BY content_hash"
    ).fetchall()
    hashes = [r[0] for r in rows]
    body = {
        "split": Split.PRIVATE.value,
        "count": len(hashes),
        "generated_at": datetime.now(UTC).isoformat(),
        "item_hashes": hashes,
    }
    path = golden_dir / "manifest_private.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def _insert_replacement_items(
    con: duckdb.DuckDBPyConnection, items: list[Item], release: str, created_at: datetime
) -> None:
    for item in items:
        con.execute(
            "INSERT INTO items (item_id, split, rubric_version, source, content_hash, "
            "created_at, introduced_release) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.item_id,
                item.split.value,
                item.rubric_version,
                item.source.value,
                item.content_hash,
                created_at,
                release,
            ),
        )
        for field in item.fields:
            con.execute(
                "INSERT INTO item_fields VALUES (?, ?, ?, ?, ?, ?)",
                (
                    item.item_id,
                    field.field_name,
                    field.field_type.value,
                    field.expected_value,
                    field.expected_normalised,
                    str(field.tolerance) if field.tolerance is not None else None,
                ),
            )


def rotate_private_split(  # noqa: PLR0913, PLR0917 -- each param is a distinct, required input
    con: duckdb.DuckDBPyConnection,
    *,
    fraction: float,
    new_seed: int,
    seed_ref: str,
    release: str,
    rubric_version: str,
    salt: str,
    repo_root: Path,
) -> RotationRecord:
    if len(salt) < _ENTROPY_FLOOR:
        raise ValueError(
            f"salt must carry at least 128 bits of entropy (>= {_ENTROPY_FLOOR} characters, "
            f'e.g. `python -c "import secrets; print(secrets.token_hex(16))"`) -- generate.py '
            "is a published module, so a short salt makes its message space brute-forceable "
            "(audit B4b)."
        )

    if not 0 < fraction < 1:
        raise ValueError(f"fraction must be in (0, 1), got {fraction!r}")

    already = con.execute("SELECT 1 FROM rotations WHERE release = ?", [release]).fetchone()
    if already is not None:
        raise ValueError(f"release {release!r} has already rotated the private split")

    count_row = con.execute(
        "SELECT count(*) FROM items WHERE split='private' AND retired_at IS NULL"
    ).fetchone()
    assert count_row is not None  # noqa: S101 -- count(*) always returns exactly one row
    active_private_count = count_row[0]
    n = round(fraction * active_private_count)

    retiring = con.execute(
        "SELECT content_hash FROM items WHERE split='private' AND retired_at IS NULL "
        "ORDER BY created_at ASC LIMIT ?",
        [n],
    ).fetchall()
    retired_hashes = [r[0] for r in retiring]

    rotated_at = datetime.now(UTC)
    con.execute(
        f"UPDATE items SET retired_at = ? WHERE content_hash IN "
        f"({','.join(['?'] * len(retired_hashes))})",
        [rotated_at, *retired_hashes],
    )

    replacements = [
        item.model_copy(update={"split": Split.PRIVATE})
        for item in generate(count=n, seed=new_seed, rubric_version=rubric_version, salt=salt)
    ]
    _insert_replacement_items(con, replacements, release, rotated_at)

    corpus_dir = repo_root / "golden" / "corpus" / "private"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for item in replacements:
        (corpus_dir / f"{item.item_id}.txt").write_text(render_document(item), encoding="utf-8")

    _write_manifest_from_db(con, repo_root / "golden")

    added_hashes = [item.content_hash for item in replacements]
    con.execute(
        "INSERT INTO rotations VALUES (?, ?, ?, ?, ?)",
        (
            release,
            rotated_at,
            json.dumps(sorted(retired_hashes)),
            json.dumps(sorted(added_hashes)),
            seed_ref,
        ),
    )

    return RotationRecord(
        release=release,
        rotated_at=rotated_at,
        retired_hashes=sorted(retired_hashes),
        added_hashes=sorted(added_hashes),
        seed_ref=seed_ref,
    )


def cohort_intersection(con: duckdb.DuckDBPyConnection, release_a: str, release_b: str) -> set[str]:
    """content_hash values of private items active in BOTH releases: introduced at or before
    the earlier release, and not retired by any rotation up to and including the later release.

    Release identifiers are ISO-date-like strings (`"YYYY.MM.DD"`), consistently sortable, so
    plain string comparison gives the correct chronological ordering.
    """
    early, late = sorted((release_a, release_b))

    excluded: set[str] = set()
    for (retired_json,) in con.execute(
        "SELECT retired_hashes FROM rotations WHERE release <= ?", [late]
    ).fetchall():
        excluded.update(json.loads(retired_json))

    rows = con.execute(
        "SELECT content_hash FROM items WHERE split='private' AND introduced_release <= ?",
        [early],
    ).fetchall()
    return {r[0] for r in rows if r[0] not in excluded}
