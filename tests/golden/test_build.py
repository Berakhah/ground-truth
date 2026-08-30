from __future__ import annotations

import json

import pytest

from ground_truth.golden import build
from ground_truth.golden.schema import Split
from ground_truth.store.db import connect


def test_require_env_raises_naming_the_short_variable():
    with pytest.raises(ValueError, match="GT_HASH_SALT"):
        build._require_env("GT_HASH_SALT")


def test_require_env_returns_a_long_enough_value_unchanged(monkeypatch):
    monkeypatch.setenv("GT_HASH_SALT", "a" * 32)
    assert build._require_env("GT_HASH_SALT") == "a" * 32


def test_build_never_imports_assign_splits():
    """audit B4a: assign_splits stays a tested pure function for
    tests/golden/test_splits.py only -- build.py's production path must never call it,
    since a pool split from one committed seed is the exact bug that leaked B4a. Checking
    the module's namespace (not its source text) avoids a false positive on this very
    docstring, which names assign_splits by way of explaining why it is absent."""
    assert not hasattr(build, "assign_splits")


def test_main_builds_two_disjoint_corpora_and_is_idempotent(tmp_path, monkeypatch):
    """Small counts by design: this exercises main()'s wiring (env vars -> two disjoint
    generate() calls -> files + manifests + DB rows -> a safe re-run), not the corpus's
    full size or its cryptographic disjointness, which tests/golden/test_splits.py
    already covers at the real 120/180 scale."""
    monkeypatch.setenv("GT_PUBLIC_SEED", "1" * 32)
    monkeypatch.setenv("GT_PRIVATE_SEED", "a" * 32)
    monkeypatch.setenv("GT_HASH_SALT", "b" * 32)

    build.main(repo_root=tmp_path, public_count=6, private_count=9)

    golden_dir = tmp_path / "golden"
    public_dir = golden_dir / "corpus" / Split.PUBLIC.value
    private_dir = golden_dir / "corpus" / Split.PRIVATE.value
    assert len(list(public_dir.glob("*.txt"))) == 6  # noqa: PLR2004
    assert len(list(private_dir.glob("*.txt"))) == 9  # noqa: PLR2004

    public_hashes = json.loads((golden_dir / "manifest_public.json").read_text())["item_hashes"]
    private_hashes = json.loads((golden_dir / "manifest_private.json").read_text())["item_hashes"]
    assert not (set(public_hashes) & set(private_hashes)), (
        "the two splits must be generated from disjoint seeds into disjoint corpora"
    )

    con = connect(tmp_path / "data" / "results.duckdb")
    counts = dict(con.execute("SELECT split, count(*) FROM items GROUP BY split").fetchall())
    con.close()
    assert counts == {"public": 6, "private": 9}

    # Re-running against the same repo_root must replace the prior build's rows, not
    # raise a PRIMARY KEY violation or double the row counts.
    build.main(repo_root=tmp_path, public_count=6, private_count=9)
    con = connect(tmp_path / "data" / "results.duckdb")
    counts_after = dict(con.execute("SELECT split, count(*) FROM items GROUP BY split").fetchall())
    field_count = con.execute("SELECT count(*) FROM item_fields").fetchone()
    con.close()
    assert counts_after == {"public": 6, "private": 9}
    assert field_count is not None and field_count[0] > 0
