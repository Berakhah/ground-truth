# tests/publish/test_release.py
"""Stage one of the two-stage release gate: cutting a release on the machine holding the
results database. See scripts/reproduce.py --require-release for stage two (CI)."""

import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ground_truth.artifact_names import RELEASE
from ground_truth.publish.artifacts import emit_all
from ground_truth.publish.release import GatesFailed, cut_release, write_attestation
from ground_truth.store.db import connect, migrate
from tests.publish.test_artifacts import seed

REPO = Path(__file__).resolve().parents[2]
AS_OF = datetime(2026, 10, 15, tzinfo=UTC)
_spec = importlib.util.spec_from_file_location("reproduce", REPO / "scripts" / "reproduce.py")
assert _spec and _spec.loader
reproduce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reproduce)


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "results.duckdb"
    con = connect(path)
    migrate(con)
    seed(con, "priv1", "private", "999.99", "hash-priv")
    con.execute("UPDATE outputs SET token_count = 500")
    con.close()
    return path


@pytest.fixture()
def models_yaml(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text(
        "slots:\n"
        "  slot-a:\n"
        "    family: acme-family\n"
        "    provider: acme-cloud\n"
        "    model_ref: acme-v1\n"
        "    trains_on_data: false\n"
        "    commercial_use: true\n"
        "    exposes_fingerprint: false\n"
        "    list_price_in_per_1m: '1.00'\n"
        "    list_price_out_per_1m: '2.00'\n"
        "    pricing_url: https://example.invalid/pricing\n"
        "    retrieved_at: 2026-09-01\n",
        encoding="utf-8",
    )
    return path


def _cut(db, out, models_yaml, gates):
    return cut_release(
        db, out, as_of=AS_OF, analysis_seed=1, models_yaml=models_yaml, run_gates=gates
    )


def test_the_attestation_lists_every_file_with_its_sha256(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "leaderboard.json").write_text('{"rows": []}', encoding="utf-8")
    (out / "regression.json").write_text("{}", encoding="utf-8")
    write_attestation(out, as_of=AS_OF, analysis_seed=7, gates=["g"])
    attestation = json.loads((out / RELEASE).read_text(encoding="utf-8"))
    assert attestation == {
        "as_of": AS_OF.isoformat(),
        "analysis_seed": 7,
        "gates": ["g"],
        "files": {
            "leaderboard.json": hashlib.sha256(b'{"rows": []}').hexdigest(),
            "regression.json": hashlib.sha256(b"{}").hexdigest(),
        },
    }


def test_a_cut_release_passes_the_ci_gate(db, tmp_path, models_yaml):
    out = tmp_path / "artifacts"
    _cut(db, out, models_yaml, lambda: True)
    assert reproduce.main(["reproduce.py", str(out), "--require-release"]) == 0


def test_failed_gates_leave_no_attestation(db, tmp_path, models_yaml):
    out = tmp_path / "artifacts"
    with pytest.raises(GatesFailed):
        _cut(db, out, models_yaml, lambda: False)
    assert not (out / RELEASE).exists()


def test_the_gates_run_against_the_freshly_emitted_artifacts(db, tmp_path, models_yaml):
    out = tmp_path / "artifacts"
    seen: list[str] = []
    _cut(db, out, models_yaml, lambda: seen.extend(p.name for p in out.iterdir()) or True)
    assert "leaderboard.json" in seen
    assert RELEASE not in seen


def test_re_emitting_drops_the_previous_attestation(db, tmp_path, models_yaml):
    """A stale release.json would vouch for bytes the gates never saw."""
    out = tmp_path / "artifacts"
    _cut(db, out, models_yaml, lambda: True)
    con = connect(db)
    try:
        emit_all(con, out, as_of=AS_OF, analysis_seed=1, models_yaml=models_yaml)
    finally:
        con.close()
    assert not (out / RELEASE).exists()


def test_a_directory_under_the_attestation_name_is_refused_not_deleted(db, tmp_path, models_yaml):
    out = tmp_path / "artifacts"
    (out / RELEASE).mkdir(parents=True)
    (out / RELEASE / "keep.txt").write_text("x", encoding="utf-8")
    con = connect(db)
    try:
        with pytest.raises(ValueError, match="refusing"):
            emit_all(con, out, as_of=AS_OF, analysis_seed=1, models_yaml=models_yaml)
    finally:
        con.close()
    assert (out / RELEASE / "keep.txt").exists()


def test_attesting_a_folder_holding_a_subdirectory_is_refused(tmp_path):
    out = tmp_path / "out"
    (out / "dump").mkdir(parents=True)
    (out / "leaderboard.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="dump"):
        write_attestation(out, as_of=AS_OF, analysis_seed=1, gates=[])
    assert not (out / RELEASE).exists()
