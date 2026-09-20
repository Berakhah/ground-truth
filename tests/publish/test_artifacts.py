# tests/publish/test_artifacts.py
import dataclasses
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ground_truth.matrix.cost import PlaceholderPricingError
from ground_truth.publish.artifacts import (
    PrivateVerdict,
    emit_all,
    emit_private_verdicts_by_hash,
    emit_public_verdicts,
)
from ground_truth.store.db import connect, migrate


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def seed(con, item_id, split, secret_value, content_hash):
    now = datetime.now(UTC)
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES (?,?,'v1','synthetic',?,?)",
        [item_id, split, content_hash, now],
    )
    con.execute(
        "INSERT INTO item_fields VALUES (?,'contract_sum','money',?,NULL,'0.01')",
        [item_id, secret_value],
    )
    con.execute(
        "INSERT INTO runs VALUES (?,?,NULL,'slot-a','ref','prov',false,'s1','sha','h')",
        [f"r-{item_id}", now],
    )
    con.execute(
        "INSERT INTO outputs VALUES (?,?,?,1,?,'call','prov',NULL,10,'ph',?,NULL)",
        [f"o-{item_id}", f"r-{item_id}", item_id, json.dumps({"contract_sum": secret_value}), now],
    )
    con.execute(
        "INSERT INTO verdicts VALUES (?,?,'contract_sum','exact','1','v1',true,'ok',?)",
        [f"v-{item_id}", f"o-{item_id}", now],
    )


def test_manifest_private_excludes_retired_items(con, tmp_path):
    """emit_all's manifest previously built its own inline query (`WHERE split = 'private'`,
    no `retired_at` filter) -- a third, drifted-out-of-sync copy of the manifest-building
    logic in golden/manifest.py and golden/rotate.py. A rotated-out item's hash must not
    keep appearing in a manifest published after its rotation, and the shape must match the
    one canonical manifest format (`split`, `count`, `generated_at`, `item_hashes`)."""
    seed(con, "priv1", "private", "999.99", "hash-priv")
    seed(con, "priv2", "private", "888.88", "hash-retired")
    con.execute("UPDATE items SET retired_at = now() WHERE item_id = 'priv2'")
    con.execute("UPDATE outputs SET token_count = 500 WHERE item_id = 'priv1'")
    real_models_yaml = tmp_path / "models.yaml"
    real_models_yaml.write_text(
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
    out_dir = tmp_path / "out"
    emit_all(
        con,
        out_dir,
        as_of=datetime(2026, 9, 7, tzinfo=UTC),
        analysis_seed=1,
        models_yaml=real_models_yaml,
    )
    manifest = json.loads((out_dir / "manifest_private.json").read_text(encoding="utf-8"))
    assert manifest["item_hashes"] == ["hash-priv"]
    assert manifest["count"] == 1
    assert manifest["split"] == "private"
    assert "generated_at" in manifest


def test_emit_all_refuses_placeholder_pricing_for_a_real_slot(con, tmp_path):
    """emit_all's default models_yaml is the repo's real, checked-in models.yaml -- which is
    explicitly an unaudited placeholder scaffold (see its own header). Real accuracy data on
    a slot that file describes ('slot-a') must not reach a published CostClaim built from
    fake prices; PlaceholderPricingError proves this end to end, not just at the cost.py
    unit level."""
    seed(con, "priv1", "private", "999.99", "hash-priv")
    con.execute("UPDATE outputs SET token_count = 500 WHERE item_id = 'priv1'")
    with pytest.raises(PlaceholderPricingError):
        emit_all(con, tmp_path, as_of=datetime(2026, 9, 7, tzinfo=UTC), analysis_seed=1)


def test_private_verdict_type_carries_no_item_id_and_no_output():
    names = {f.name for f in dataclasses.fields(PrivateVerdict)}
    assert "item_id" not in names and "raw_output" not in names


def test_public_verdicts_include_item_ids(con, tmp_path):
    seed(con, "pub1", "public", "111.11", "hash-pub")
    path = tmp_path / "verdicts_public.jsonl"
    assert emit_public_verdicts(con, path) == 1
    assert "pub1" in path.read_text(encoding="utf-8")


def test_private_verdicts_are_keyed_by_hash_only(con, tmp_path):
    seed(con, "priv1", "private", "999.99", "hash-priv")
    path = tmp_path / "verdicts_private.jsonl"
    assert emit_private_verdicts_by_hash(con, path) == 1
    body = path.read_text(encoding="utf-8")
    assert "hash-priv" in body
    assert "priv1" not in body, "private item ids must never be published"
    assert "999.99" not in body, "private labels must never be published"


def test_public_and_private_emitters_do_not_cross_contaminate(con, tmp_path):
    seed(con, "pub1", "public", "111.11", "hash-pub")
    seed(con, "priv1", "private", "999.99", "hash-priv")
    pub, priv = tmp_path / "pub.jsonl", tmp_path / "priv.jsonl"
    emit_public_verdicts(con, pub)
    emit_private_verdicts_by_hash(con, priv)
    assert "priv1" not in pub.read_text(encoding="utf-8")
    assert "pub1" not in priv.read_text(encoding="utf-8")


def test_output_is_byte_stable(con, tmp_path):
    seed(con, "pub1", "public", "111.11", "hash-pub")
    path = tmp_path / "v.jsonl"
    emit_public_verdicts(con, path)
    first = path.read_text(encoding="utf-8")
    emit_public_verdicts(con, path)
    assert path.read_text(encoding="utf-8") == first


def test_every_line_is_valid_json(con, tmp_path):
    seed(con, "pub1", "public", "111.11", "hash-pub")
    path = tmp_path / "v.jsonl"
    emit_public_verdicts(con, path)
    for line in path.read_text(encoding="utf-8").splitlines():
        json.loads(line)


def test_empty_split_writes_an_empty_file_not_a_crash(con, tmp_path):
    path = tmp_path / "v.jsonl"
    assert emit_private_verdicts_by_hash(con, path) == 0
    assert path.read_text(encoding="utf-8") == ""


def test_judge_agreement_decided_at_is_utc_normalised(con, tmp_path):
    """Review finding (task-40): a bare CAST(decided_at AS VARCHAR) renders in duckdb's
    session TimeZone, which defaults to the host's local OS timezone and is never pinned in
    this repo -- so the same stored instant would render differently on two machines,
    breaking byte-for-byte reproducibility. Pin a non-UTC session zone here to prove the fix
    holds independent of the host, not just "happens to pass" on a UTC CI runner."""
    con.execute("SET TimeZone='America/New_York'")
    con.execute(
        "INSERT INTO judge_decisions VALUES "
        "('money','v1',0.9,0.8,0.95,40,0.8,'accepted','2026-09-04 15:34:56.789+03')"
    )
    out_dir = tmp_path / "out"
    emit_all(con, out_dir, as_of=datetime(2026, 9, 7, tzinfo=UTC), analysis_seed=1)
    decided_at = json.loads((out_dir / "judge_agreement.json").read_text(encoding="utf-8"))[
        "decisions"
    ][0]["decided_at"]
    assert decided_at == "2026-09-04 12:34:56.789", decided_at
    assert not decided_at.endswith(("+03", "-04")), "must not carry a session-timezone offset"


def test_cli_entrypoint_writes_artifacts_to_out_dir(tmp_path):
    """Task 49 Step 1: publish.yml's own release command runs this as
    `python -m ground_truth.publish.artifacts --out ... --as-of ...`."""
    db_path = tmp_path / "t.duckdb"
    con = connect(db_path)
    migrate(con)
    con.close()
    out_dir = tmp_path / "out"
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ground_truth.publish.artifacts",
            "--db",
            str(db_path),
            "--out",
            str(out_dir),
            "--as-of",
            "2026-10-15T00:00:00+00:00",
            "--analysis-seed",
            "1",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (out_dir / "leaderboard.json").exists()
