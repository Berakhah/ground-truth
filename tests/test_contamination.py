# tests/test_contamination.py
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ground_truth.artifact_names import REGRESSION, TRIAGE_EXAMPLE
from ground_truth.publish.artifacts import emit_all
from ground_truth.store.db import connect
from tests.conftest import require_or_skip, require_sweep_data

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "results.duckdb"
AS_OF = datetime(2026, 10, 15, tzinfo=UTC)


@pytest.fixture()
def emitted(tmp_path):
    require_or_skip(DB.exists(), "run the sweep first")
    con = connect(DB)
    require_sweep_data(con, "run the sweep first")
    # Publish over the committed carried files, as the release job does, and scan everything
    # left in the folder -- not only what emit_all regenerates (re-review 2026-09-28).
    out = tmp_path / "out"
    out.mkdir()
    for name in (TRIAGE_EXAMPLE, REGRESSION):
        if (REPO / "artifacts" / name).is_file():
            shutil.copy2(REPO / "artifacts" / name, out / name)
    emit_all(con, out, as_of=AS_OF, analysis_seed=1)
    paths = sorted(p for p in out.iterdir() if p.is_file())
    yield con, paths
    con.close()


def test_private_item_ids_never_appear_in_published_output(emitted):
    """Depends on Phase 1's item_id fix (audit H1).

    item_id was content_hash[:16] -- a PREFIX of the hash that manifest_private.json and
    verdicts_private_by_hash.jsonl both publish -- so this assertion could never pass, and
    the finding was real rather than a test artifact: publishing the hash published the id.
    Phase 1 Task 8 now derives item_id = sha256(b"item-id:" + content_hash)[:16].
    """
    con, paths = emitted
    ids = {r[0] for r in con.execute("SELECT item_id FROM items WHERE split='private'").fetchall()}
    for path in paths:
        blob = path.read_text(encoding="utf-8")
        leaked = sorted(i for i in ids if i in blob)
        assert leaked == [], f"{path.name} leaks private item ids: {leaked[:5]}"


def test_private_labels_never_appear_in_published_output(emitted):
    """High-entropy field types only -- see audit M10.

    The original scanned every private expected_value longer than 6 characters. Private
    labels include "2026-09-01" (in every artifact carrying a date), "approved", and
    PARTY_NAME strings shared with public items, so spurious failures were certain and the
    obvious response -- raising the length threshold until it passes -- silently disables
    the control. Restricting to MONEY / PERCENT / IDENTIFIER keeps the signal.
    """
    con, paths = emitted
    values = {
        r[0]
        for r in con.execute(
            "SELECT f.expected_value FROM item_fields f JOIN items i ON i.item_id = f.item_id "
            "WHERE i.split='private' AND f.field_type IN ('money','percent','identifier')"
        ).fetchall()
        if len(r[0]) > 6  # noqa: PLR2004
    }
    for path in paths:
        blob = path.read_text(encoding="utf-8")
        leaked = sorted(v for v in values if v in blob)
        assert leaked == [], f"{path.name} leaks private labels: {leaked[:5]}"


def test_private_emitter_never_reads_the_columns_it_must_not_publish():
    """The structural guarantee, which holds regardless of what any scan happens to catch."""
    import inspect  # noqa: PLC0415

    from ground_truth.publish import artifacts  # noqa: PLC0415

    src = inspect.getsource(artifacts.emit_private_verdicts_by_hash)
    for column in ("expected_value", "raw_output", "item_id"):
        assert column not in src, f"the safest way not to publish {column} is not to read it"


def test_triage_output_is_never_a_published_artifact(emitted):
    """audit B2: the triage deliverable is CLIENT_CONFIDENTIAL (00 R4) and artifacts/ deploys."""
    _, paths = emitted
    assert not any(p.name == "triage.html" for p in paths)


def test_no_client_quote_appears_in_any_published_artifact(emitted):
    import csv  # noqa: PLC0415

    _, paths = emitted
    intake_dir = REPO / "deliverables"
    if not intake_dir.exists():
        pytest.skip("no client intake present")
    quotes = {
        r["client_quote"]
        for p in intake_dir.glob("*.csv")
        for r in csv.DictReader(p.open(encoding="utf-8"))
        if r["client_quote"]
    }
    for path in paths:
        blob = path.read_text(encoding="utf-8")
        leaked = sorted(q for q in quotes if q in blob)
        assert leaked == [], f"{path.name} leaks a client's verbatim words"


def test_private_model_outputs_never_appear_in_published_output(emitted):
    con, paths = emitted
    outputs = {
        r[0]
        for r in con.execute(
            "SELECT o.raw_output FROM outputs o JOIN items i ON i.item_id = o.item_id "
            "WHERE i.split='private'"
        ).fetchall()
    }
    for path in paths:
        blob = path.read_text(encoding="utf-8")
        for out in outputs:
            assert out not in blob, f"{path.name} leaks a private model output"


def test_published_hashes_match_the_manifest(emitted):
    con, paths = emitted
    manifest = next(p for p in paths if p.name == "manifest_private.json")
    published = set(json.loads(manifest.read_text(encoding="utf-8"))["item_hashes"])
    actual = {
        r[0]
        for r in con.execute(
            "SELECT content_hash FROM items WHERE split='private' AND retired_at IS NULL"
        ).fetchall()
    }
    assert published == actual


def test_private_corpus_not_tracked_by_git():
    out = subprocess.run(
        ["git", "ls-files", "golden/corpus/private/"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [p for p in out.stdout.splitlines() if p.strip() and not p.endswith(".gitkeep")]
    assert tracked == []


def test_private_seed_not_tracked_by_git():
    out = subprocess.run(
        ["git", "ls-files", ".env"], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == ""


PRIVATE_CORPUS = REPO / "golden" / "corpus" / "private"
PUBLIC_CORPUS = REPO / "golden" / "corpus" / "public"
MIN_DISTINCTIVE_LINE = 20


def _private_fingerprints() -> tuple[set[str], set[str]]:
    """Private item ids (the corpus file names) and the private-document lines that appear in
    no public document -- shared boilerplate would match everywhere and teach people to ignore
    the test (audit M10's lesson for labels)."""
    public_lines = {
        line.strip()
        for p in PUBLIC_CORPUS.glob("*.txt")
        for line in p.read_text(encoding="utf-8").splitlines()
    }
    ids = {p.stem for p in PRIVATE_CORPUS.glob("*.txt")}
    lines = {
        line.strip()
        for p in PRIVATE_CORPUS.glob("*.txt")
        for line in p.read_text(encoding="utf-8").splitlines()
        if len(line.strip()) >= MIN_DISTINCTIVE_LINE and line.strip() not in public_lines
    }
    return ids, lines


def _leaks(files: list[Path], ids: set[str], lines: set[str]) -> list[str]:
    found = []
    for path in files:
        blob = path.read_text(encoding="utf-8")
        found += [f"{path.name}: id {i}" for i in sorted(ids) if i in blob]
        found += [f"{path.name}: line {line!r}" for line in sorted(lines) if line in blob]
    return found


def test_the_committed_artifact_scan_catches_a_planted_leak(tmp_path):
    """The control can fail: a file carrying a private id or a private-only line is caught."""
    planted = tmp_path / "regression.json"
    planted.write_text('{"note": "abc0123456789def INV-PRIVATE-ONLY 00042 total due"}', "utf-8")
    found = _leaks([planted], {"abc0123456789def"}, {"INV-PRIVATE-ONLY 00042 total due"})
    assert len(found) == 2  # noqa: PLR2004


def test_committed_artifacts_carry_no_private_item_content():
    """Re-review 2026-09-28 (security): a hand-committed regression.json and the triage
    example are carried into every publish and bundled into the site, but the DB-backed gates
    above scan only what emit_all regenerates. This scans every committed file in artifacts/
    against the private corpus directly, so it runs wherever the corpus exists -- no sweep
    database needed. The corpus is gitignored, so a fresh checkout (CI) skips."""
    if not any(PRIVATE_CORPUS.glob("*.txt")):
        pytest.skip("private corpus not present (gitignored); run golden.build")
    ids, lines = _private_fingerprints()
    assert ids and lines, "the fingerprint set is empty, so the scan would pass vacuously"
    committed = sorted(p for p in (REPO / "artifacts").iterdir() if p.is_file())
    assert _leaks(committed, ids, lines) == []
