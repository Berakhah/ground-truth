"""python -m ground_truth.golden.build

Builds the shipped golden corpus: 120 public items and 180 private items, generated
from two independent seeds (`GT_PUBLIC_SEED`, `GT_PRIVATE_SEED`) plus a hash salt
(`GT_HASH_SALT`), all read from the environment.

audit B4a: the public and private corpora are generated as two disjoint calls to
`generate`, never by generating one pool and splitting it with `assign_splits`. A pool
split from one committed seed would let anyone who has that seed (it ships in
`.env.example`) regenerate the pool and recover the "private" labels. `assign_splits`
stays a tested pure function (see `tests/golden/test_splits.py`) but is never called
here.

audit B4b: `generate.py` is a published module, so a short/guessable seed or salt makes
its message space brute-forceable. All three environment variables must carry at least
128 bits of entropy (>= 32 characters, e.g. `secrets.token_hex(16)`) or this script
refuses to run.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from ground_truth.golden.generate import generate, render_document
from ground_truth.golden.manifest import write_manifest
from ground_truth.golden.schema import Item, Split
from ground_truth.store.db import connect, migrate

_ENTROPY_FLOOR = 32  # characters; 128 bits, matching secrets.token_hex(16)'s output length
_REPO = Path(__file__).resolve().parents[2]


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if len(value) < _ENTROPY_FLOOR:
        raise ValueError(
            f"{name} must carry at least 128 bits of entropy (>= {_ENTROPY_FLOOR} characters, "
            f'e.g. `python -c "import secrets; print(secrets.token_hex(16))"`) -- generate.py '
            f"is a published module, so a short {name} makes its message space brute-forceable "
            "(audit B4b)."
        )
    return value


def _write_corpus(items: list[Item], split_dir: Path) -> None:
    # Full rebuild semantics, matching _insert_items: a reseed must replace the prior
    # build's files, not pile the old seed's items up alongside the new ones.
    split_dir.mkdir(parents=True, exist_ok=True)
    for stale in split_dir.glob("*.txt"):
        stale.unlink()
    for item in items:
        (split_dir / f"{item.item_id}.txt").write_text(render_document(item), encoding="utf-8")


def _insert_items(con: duckdb.DuckDBPyConnection, items: list[Item]) -> None:
    # Full rebuild semantics: a second `python -m ground_truth.golden.build` against an
    # existing data/results.duckdb replaces the prior build's rows rather than raising a
    # PRIMARY KEY violation on `items`/`item_fields`.
    con.execute("DELETE FROM item_fields")
    con.execute("DELETE FROM items")
    created_at = datetime.now(UTC)
    for item in items:
        con.execute(
            "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?)",
            (
                item.item_id,
                item.split.value,
                item.rubric_version,
                item.source.value,
                item.content_hash,
                created_at,
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


def main(repo_root: Path = _REPO, public_count: int = 120, private_count: int = 180) -> None:
    public_seed = _require_env("GT_PUBLIC_SEED")
    private_seed = _require_env("GT_PRIVATE_SEED")
    hash_salt = _require_env("GT_HASH_SALT")

    public_items = generate(
        count=public_count, seed=int(public_seed), rubric_version="v1", salt=hash_salt
    )
    private_items = [
        item.model_copy(update={"split": Split.PRIVATE})
        for item in generate(
            count=private_count, seed=private_seed, rubric_version="v1", salt=hash_salt
        )
    ]

    golden_dir = repo_root / "golden"
    _write_corpus(public_items, golden_dir / "corpus" / Split.PUBLIC.value)
    _write_corpus(private_items, golden_dir / "corpus" / Split.PRIVATE.value)
    write_manifest(public_items, Split.PUBLIC, golden_dir / "manifest_public.json")
    write_manifest(private_items, Split.PRIVATE, golden_dir / "manifest_private.json")

    db_con = connect(repo_root / "data" / "results.duckdb")
    migrate(db_con)
    try:
        _insert_items(db_con, public_items + private_items)
    finally:
        db_con.close()


if __name__ == "__main__":
    main()
