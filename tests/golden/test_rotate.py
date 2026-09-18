from datetime import UTC, datetime

import pytest

from ground_truth.golden.rotate import cohort_intersection, rotate_private_split
from ground_truth.store.db import connect, migrate

_SALT = "test-salt-not-for-production-only-32chars"


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    for i in range(100):
        c.execute(
            "INSERT INTO items (item_id, split, rubric_version, source, content_hash, "
            "created_at, introduced_release) VALUES (?,'private','v1','synthetic',?,?,?)",
            [f"i{i}", f"hash-{i}", datetime(2026, 10, 1, tzinfo=UTC), "2026.10.15"],
        )
    yield c
    c.close()


def test_rotation_replaces_the_requested_fraction(con, tmp_path):
    record = rotate_private_split(
        con,
        fraction=0.20,
        new_seed=99,
        seed_ref="GT_PRIVATE_SEED_2027Q1",
        release="2027.01.15",
        rubric_version="v1",
        salt=_SALT,
        repo_root=tmp_path,
    )
    assert len(record.retired_hashes) == 20 and len(record.added_hashes) == 20  # noqa: PLR2004


def test_active_split_size_is_unchanged_after_rotation(con, tmp_path):
    before = con.execute(
        "SELECT count(*) FROM items WHERE split='private' AND retired_at IS NULL"
    ).fetchone()[0]
    rotate_private_split(
        con,
        fraction=0.20,
        new_seed=99,
        seed_ref="ref",
        release="2027.01.15",
        rubric_version="v1",
        salt=_SALT,
        repo_root=tmp_path,
    )
    after = con.execute(
        "SELECT count(*) FROM items WHERE split='private' AND retired_at IS NULL"
    ).fetchone()[0]
    assert after == before, "rotation replaces items; it does not grow or shrink the active split"


def test_retired_items_are_marked_not_deleted(con, tmp_path):
    record = rotate_private_split(
        con,
        fraction=0.20,
        new_seed=99,
        seed_ref="ref",
        release="2027.01.15",
        rubric_version="v1",
        salt=_SALT,
        repo_root=tmp_path,
    )
    for h in record.retired_hashes:
        row = con.execute("SELECT retired_at FROM items WHERE content_hash = ?", [h]).fetchone()
        assert row is not None and row[0] is not None, (
            "retired items stay in the database -- historical verdicts must remain valid"
        )


def test_rotation_record_stores_a_seed_name_never_a_seed_value(con, tmp_path):
    record = rotate_private_split(
        con,
        fraction=0.20,
        new_seed=12345,
        seed_ref="GT_SEED_2027Q1",
        release="2027.01.15",
        rubric_version="v1",
        salt=_SALT,
        repo_root=tmp_path,
    )
    assert record.seed_ref == "GT_SEED_2027Q1"
    assert "12345" not in str(record), "publishing the seed would let anyone rebuild the split"


def test_rotation_is_recorded_for_audit(con, tmp_path):
    rotate_private_split(
        con,
        fraction=0.20,
        new_seed=99,
        seed_ref="ref",
        release="2027.01.15",
        rubric_version="v1",
        salt=_SALT,
        repo_root=tmp_path,
    )
    assert con.execute("SELECT count(*) FROM rotations").fetchone()[0] == 1


def test_cohort_intersection_excludes_rotated_items(con, tmp_path):
    record = rotate_private_split(
        con,
        fraction=0.20,
        new_seed=99,
        seed_ref="ref",
        release="2027.01.15",
        rubric_version="v1",
        salt=_SALT,
        repo_root=tmp_path,
    )
    shared = cohort_intersection(con, "2026.10.15", "2027.01.15")
    assert len(shared) == 80  # noqa: PLR2004
    assert not (shared & set(record.retired_hashes))
    assert not (shared & set(record.added_hashes))


def test_rotating_twice_in_one_release_raises(con, tmp_path):
    rotate_private_split(
        con,
        fraction=0.20,
        new_seed=99,
        seed_ref="ref",
        release="2027.01.15",
        rubric_version="v1",
        salt=_SALT,
        repo_root=tmp_path,
    )
    with pytest.raises(ValueError, match="already rotated"):
        rotate_private_split(
            con,
            fraction=0.20,
            new_seed=100,
            seed_ref="ref2",
            release="2027.01.15",
            rubric_version="v1",
            salt=_SALT,
            repo_root=tmp_path,
        )


def test_fraction_out_of_range_raises(con, tmp_path):
    with pytest.raises(ValueError):
        rotate_private_split(
            con,
            fraction=1.5,
            new_seed=99,
            seed_ref="ref",
            release="2027.01.15",
            rubric_version="v1",
            salt=_SALT,
            repo_root=tmp_path,
        )


def test_short_salt_is_refused(con, tmp_path):
    with pytest.raises(ValueError, match="entropy"):
        rotate_private_split(
            con,
            fraction=0.20,
            new_seed=99,
            seed_ref="ref",
            release="2027.01.15",
            rubric_version="v1",
            salt="too-short",
            repo_root=tmp_path,
        )
