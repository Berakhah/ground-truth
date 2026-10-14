# tests/test_reproduce_script.py
"""scripts/reproduce.py is both the stranger's check and the release job's DB-free gate.

CI never holds data/results.duckdb (it carries private-split outputs), so the DB-backed gates
run when a release is cut locally, and `ground_truth.publish.release` then writes
`release.json`: the sha256 of every artifact that passed them. In CI, `--require-release`
makes reproduce.py refuse anything those gates did not see.
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("reproduce", REPO / "scripts" / "reproduce.py")
assert _spec and _spec.loader
reproduce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reproduce)

AS_OF = "2026-10-15T00:00:00+00:00"


def _release(out: Path, *, point: float = 0.75, placeholder: bool = False) -> Path:
    """Two items under one slot: item h1 1/2 correct, h2 1/1 -> mean of means 0.75."""
    out.mkdir(parents=True, exist_ok=True)
    board: dict[str, object] = {
        "rows": [{"slot": "slot-a", "accuracy": {"point": point}}],
        "as_of": AS_OF,
        "analysis_seed": 1,
    }
    if placeholder:
        board["placeholder"] = True
    (out / "leaderboard.json").write_text(json.dumps(board), encoding="utf-8")
    verdicts = [
        {"content_hash": "h1", "slot": "slot-a", "correct": True},
        {"content_hash": "h1", "slot": "slot-a", "correct": False},
        {"content_hash": "h2", "slot": "slot-a", "correct": True},
    ]
    (out / "verdicts_private_by_hash.jsonl").write_text(
        "".join(json.dumps(v) + "\n" for v in verdicts), encoding="utf-8"
    )
    return out


def _attest(out: Path, **overrides: object) -> None:
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.iterdir())
        if p.is_file() and p.name != "release.json"
    }
    attestation = {"as_of": AS_OF, "analysis_seed": 1, "gates": [], "files": files}
    attestation.update(overrides)
    (out / "release.json").write_text(json.dumps(attestation), encoding="utf-8")


def _run(out: Path, *flags: str) -> int:
    return int(reproduce.main(["reproduce.py", str(out), *flags]))


def test_a_matching_release_reproduces(tmp_path):
    assert _run(_release(tmp_path / "a")) == 0


def test_a_wrong_headline_does_not_reproduce(tmp_path):
    assert _run(_release(tmp_path / "a", point=0.80)) == 1


def _append_verdict(out: Path, verdict: dict[str, object]) -> None:
    with (out / "verdicts_private_by_hash.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(verdict) + "\n")


def test_a_verdict_flagged_as_not_counting_is_left_out_of_the_recompute(tmp_path):
    """Review 2026-10-14, I3: the file publishes verdicts the headline does not count (schema
    checks, judges without an accepted decision, retired items); each says so in
    `counts_toward_headline`, and the recompute must honour it or it cannot reach the
    published number."""
    out = _release(tmp_path / "a")
    _append_verdict(
        out,
        {"content_hash": "h2", "slot": "slot-a", "correct": False, "counts_toward_headline": False},
    )
    assert _run(out) == 0


def test_a_verdict_flagged_as_counting_is_recomputed(tmp_path):
    out = _release(tmp_path / "a")
    _append_verdict(
        out,
        {"content_hash": "h2", "slot": "slot-a", "correct": False, "counts_toward_headline": True},
    )
    assert _run(out) == 1  # h2 is now 1/2, so 0.5 != the published 0.75


def test_placeholder_data_is_refused_not_reproduced(tmp_path, capsys):
    """The committed demo artifacts would otherwise be 'reproduced' and pass a release gate."""
    assert _run(_release(tmp_path / "a", placeholder=True)) == 1
    assert "placeholder" in capsys.readouterr().out


def test_placeholder_data_in_any_artifact_is_refused(tmp_path):
    out = _release(tmp_path / "a")
    (out / "calibration.json").write_text('{"placeholder": true}', encoding="utf-8")
    assert _run(out) == 1


def test_an_empty_leaderboard_is_refused_rather_than_passing_vacuously(tmp_path):
    out = _release(tmp_path / "a")
    (out / "leaderboard.json").write_text(json.dumps({"rows": [], "as_of": AS_OF}), "utf-8")
    assert _run(out) == 1


def test_require_release_refuses_a_folder_with_no_attestation(tmp_path, capsys):
    assert _run(_release(tmp_path / "a"), "--require-release") == 1
    assert "release.json" in capsys.readouterr().out


def test_an_attested_release_passes_the_release_gate(tmp_path):
    out = _release(tmp_path / "a")
    _attest(out)
    assert _run(out, "--require-release") == 0


def test_an_artifact_edited_after_the_gates_ran_is_refused(tmp_path, capsys):
    out = _release(tmp_path / "a")
    _attest(out)
    with (out / "verdicts_private_by_hash.jsonl").open("a", encoding="utf-8") as f:
        f.write("\n")  # still reproduces, but these are not the bytes the gates saw
    assert _run(out, "--require-release") == 1
    assert "verdicts_private_by_hash.jsonl" in capsys.readouterr().out


def test_a_file_the_gates_never_saw_is_refused(tmp_path, capsys):
    """An unattested file would be deployed without having been scanned for private content."""
    out = _release(tmp_path / "a")
    _attest(out)
    (out / "triage.html").write_text("client data", encoding="utf-8")
    assert _run(out, "--require-release") == 1
    assert "triage.html" in capsys.readouterr().out


def test_an_attested_file_that_is_missing_is_refused(tmp_path):
    out = _release(tmp_path / "a")
    (out / "calibration.json").write_text("{}", encoding="utf-8")
    _attest(out)
    (out / "calibration.json").unlink()
    assert _run(out, "--require-release") == 1


@pytest.mark.parametrize(
    ("field", "value"), [("as_of", "2026-11-01T00:00:00+00:00"), ("analysis_seed", 2)]
)
def test_an_attestation_from_a_different_emit_is_refused(tmp_path, field, value):
    out = _release(tmp_path / "a")
    _attest(out, **{field: value})
    assert _run(out, "--require-release") == 1


def test_a_subdirectory_the_gates_never_saw_is_refused(tmp_path, capsys):
    """Security review 2026-09-29: a directory dropped into artifacts/ after the cut was
    invisible to the is_file() listing, so it passed the gate into the tagged commit."""
    out = _release(tmp_path / "a")
    _attest(out)
    (out / "dump").mkdir()
    (out / "dump" / "private_rows.jsonl").write_text("{}", encoding="utf-8")
    assert _run(out, "--require-release") == 1
    assert "dump" in capsys.readouterr().out
