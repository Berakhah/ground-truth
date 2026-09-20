from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from ground_truth.golden.schema import Item, Split


def _hashes(items: list[Item], split: Split) -> list[str]:
    return sorted(i.content_hash for i in items if i.split is split)


def write_manifest(items: list[Item], split: Split, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hashes = _hashes(items, split)
    body = {
        "split": split.value,
        "count": len(hashes),
        "generated_at": datetime.now(UTC).isoformat(),
        "item_hashes": hashes,
    }
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def write_manifest_from_db(con: duckdb.DuckDBPyConnection, split: Split, path: Path) -> None:
    """Same manifest shape as `write_manifest`, built directly from the store instead of an
    in-memory `Item` list -- for callers (rotation, publish) that only have DB rows, not full
    `Item` objects with fields/layout recoverable. Only *active* items count: a retired item's
    hash must not keep appearing in a manifest computed after its rotation."""
    rows = con.execute(
        "SELECT content_hash FROM items WHERE split = ? AND retired_at IS NULL "
        "ORDER BY content_hash",
        [split.value],
    ).fetchall()
    hashes = [r[0] for r in rows]
    body = {
        "split": split.value,
        "count": len(hashes),
        "generated_at": datetime.now(UTC).isoformat(),
        "item_hashes": hashes,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def verify_manifest(items: list[Item], path: Path) -> None:
    body = json.loads(path.read_text(encoding="utf-8"))
    expected = _hashes(items, Split(body["split"]))
    if expected != body["item_hashes"]:
        raise ValueError("manifest mismatch: published hashes do not match the corpus")
