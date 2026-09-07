from datetime import UTC, datetime

import pytest

from ground_truth.regression.fingerprint import FingerprintStatus, observe_fingerprints
from ground_truth.store.db import connect, migrate


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def seed(con, slot: str, fingerprints: list[str | None]) -> None:
    run_id = f"run-{slot}"
    con.execute(
        "INSERT INTO runs VALUES (?,?,NULL,?,'ref','prov',false,'sweep-1','sha','h')",
        [run_id, datetime.now(UTC), slot],
    )
    for i, fp in enumerate(fingerprints):
        con.execute(
            "INSERT INTO outputs VALUES (?,?,?,1,'{}','call','prov',?,10,'ph',?)",
            [f"{slot}-{i}", run_id, f"i{i}", fp, datetime.now(UTC)],
        )


def test_stable_fingerprint_is_reported_stable(con):
    seed(con, "slot-a", ["fp-1"] * 5)
    result = observe_fingerprints(con, "sweep-1")[0]
    assert result.status is FingerprintStatus.STABLE and result.values == ["fp-1"]


def test_changed_fingerprint_is_detected(con):
    seed(con, "slot-a", ["fp-1", "fp-1", "fp-2"])
    result = observe_fingerprints(con, "sweep-1")[0]
    assert result.status is FingerprintStatus.CHANGED
    assert set(result.values) == {"fp-1", "fp-2"}


def test_absent_fingerprint_is_reported_as_not_exposed(con):
    seed(con, "slot-a", [None] * 5)
    assert observe_fingerprints(con, "sweep-1")[0].status is FingerprintStatus.NOT_EXPOSED


def test_not_exposed_statement_does_not_imply_a_pinned_version(con):
    seed(con, "slot-a", [None] * 5)
    statement = observe_fingerprints(con, "sweep-1")[0].statement
    assert "does not expose" in statement
    assert "cannot pin" in statement, (
        "04 B6: say so rather than implying we can pin a version we cannot"
    )


def test_changed_statement_names_both_values(con):
    seed(con, "slot-a", ["fp-1", "fp-2"])
    statement = observe_fingerprints(con, "sweep-1")[0].statement
    assert "fp-1" in statement and "fp-2" in statement


def test_partial_exposure_counts_as_changed(con):
    seed(con, "slot-a", ["fp-1", None, "fp-1"])
    assert observe_fingerprints(con, "sweep-1")[0].status is FingerprintStatus.CHANGED


def test_every_slot_in_the_sweep_is_reported(con):
    seed(con, "slot-a", ["fp-1"])
    seed(con, "slot-b", [None])
    assert {r.slot for r in observe_fingerprints(con, "sweep-1")} == {"slot-a", "slot-b"}
