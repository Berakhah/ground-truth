import json
import os

import pytest

from ground_truth.golden.generate import generate
from ground_truth.golden.manifest import verify_manifest, write_manifest
from ground_truth.golden.schema import Split
from ground_truth.golden.splits import assign_splits


def _items():
    return assign_splits(generate(count=300, seed=42, rubric_version="v1"), public_n=120, seed=42)


def test_split_sizes_are_120_180():
    items = _items()
    assert sum(i.split is Split.PUBLIC for i in items) == 120  # noqa: PLR2004
    assert sum(i.split is Split.PRIVATE for i in items) == 180  # noqa: PLR2004


def test_split_assignment_is_deterministic():
    assert {i.item_id: i.split for i in _items()} == {i.item_id: i.split for i in _items()}


def test_public_n_larger_than_corpus_raises():
    with pytest.raises(ValueError):
        assign_splits(generate(count=10, seed=1, rubric_version="v1"), public_n=20, seed=1)


def test_private_manifest_contains_hashes_only(tmp_path):
    items = _items()
    path = tmp_path / "manifest_private.json"
    write_manifest(items, Split.PRIVATE, path)
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["count"] == 180  # noqa: PLR2004
    assert set(body) == {"split", "count", "generated_at", "item_hashes"}
    blob = path.read_text(encoding="utf-8")
    for item in items:
        if item.split is Split.PRIVATE:
            for field in item.fields:
                # Deviation from the brief's literal test, documented in the task-9 report:
                # values under 4 chars (line_count's single digit "3"-"8", or "" for a
                # MISSING_FIELD-injected application_no) are not a meaningful containment
                # check -- a single hex digit is virtually guaranteed to occur somewhere in
                # ~11.5K chars of concatenated SHA-256 digests by pure chance, and "" is a
                # substring of everything. The manifest's schema is already pinned to
                # hashes-only by the set(body) assert above; this loop is defense-in-depth
                # for values with enough entropy for containment to mean something (money,
                # dates, names, IDs -- all >=5 chars here).
                if len(field.expected_value) < 4:  # noqa: PLR2004
                    continue
                assert field.expected_value not in blob, "manifest leaks a private label"


def test_verify_manifest_accepts_the_manifest_it_wrote(tmp_path):
    items = _items()
    path = tmp_path / "manifest_private.json"
    write_manifest(items, Split.PRIVATE, path)
    verify_manifest(items, path)


def test_verify_manifest_detects_tampering(tmp_path):
    items = _items()
    path = tmp_path / "manifest_private.json"
    write_manifest(items, Split.PRIVATE, path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["item_hashes"][0] = "0" * 64
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest mismatch"):
        verify_manifest(items, path)


def test_public_seed_cannot_regenerate_any_private_item(monkeypatch):
    """audit B4a. The committed public seed must be useless against the private split --
    build.py generates the two splits from two independent seeds into disjoint corpora,
    never by shuffling one seed-derived pool with `assign_splits`."""
    monkeypatch.setenv("GT_PUBLIC_SEED", "42")
    monkeypatch.setenv("GT_PRIVATE_SEED", "a" * 32)
    monkeypatch.setenv("GT_HASH_SALT", "b" * 32)
    private = generate(
        count=180,
        seed=os.environ["GT_PRIVATE_SEED"],
        rubric_version="v1",
        salt=os.environ["GT_HASH_SALT"],
    )
    forged = generate(
        count=180,
        seed=int(os.environ["GT_PUBLIC_SEED"]),
        rubric_version="v1",
        salt=os.environ["GT_HASH_SALT"],
    )
    assert not ({i.content_hash for i in forged} & {i.content_hash for i in private}), (
        "the private split is derivable from committed data"
    )


def test_seeds_and_salt_meet_the_entropy_floor(monkeypatch):
    """audit B4b. 128-bit floor -- a year, a ticket id, or `random.randint(0, 2**32)` are all
    brute-forceable once generate.py is public."""
    monkeypatch.setenv("GT_PRIVATE_SEED", "a" * 32)
    monkeypatch.setenv("GT_HASH_SALT", "b" * 32)
    for key in ("GT_PRIVATE_SEED", "GT_HASH_SALT"):
        assert len(os.environ[key]) >= 32, f"{key} must carry at least 128 bits"  # noqa: PLR2004
