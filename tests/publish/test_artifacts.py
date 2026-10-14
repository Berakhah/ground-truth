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
    write_json,
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
        emit_all(con, tmp_path / "out", as_of=datetime(2026, 9, 7, tzinfo=UTC), analysis_seed=1)


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
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at) VALUES "
        "('money','judge-a','v1',0.9,0.8,0.95,40,0.8,'accepted','2026-09-04 15:34:56.789+03')"
    )
    out_dir = tmp_path / "out"
    emit_all(con, out_dir, as_of=datetime(2026, 9, 7, tzinfo=UTC), analysis_seed=1)
    decided_at = json.loads((out_dir / "judge_agreement.json").read_text(encoding="utf-8"))[
        "decisions"
    ][0]["decided_at"]
    assert decided_at == "2026-09-04 12:34:56.789", decided_at
    assert not decided_at.endswith(("+03", "-04")), "must not carry a session-timezone offset"


def test_undefined_judge_alpha_publishes_as_null_not_nan(con, tmp_path):
    """`assess` stores NaN for an alpha that is 0/0 (every unit one verdict); `json.dumps`
    would write that as the bare token NaN, which is not JSON and breaks every consumer."""
    con.execute(
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at) VALUES "
        "('money','judge-a','v1','NaN'::DOUBLE,'NaN'::DOUBLE,'NaN'::DOUBLE,60,0.667,'rejected',"
        "'2026-09-27 08:00:00+00')"
    )
    out_dir = tmp_path / "out"
    emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    text = (out_dir / "judge_agreement.json").read_text(encoding="utf-8")
    decision = json.loads(text, parse_constant=_reject_non_json_constant)["decisions"][0]
    assert (decision["alpha"], decision["alpha_low"], decision["alpha_high"]) == (None, None, None)
    assert decision["status"] == "rejected"


def test_judge_decisions_publish_the_stored_statement_and_interval_method(con, tmp_path):
    """The publisher publishes what `assess` wrote -- its statement and the interval's method,
    which carries the count of excluded 0/0 resamples methodology.md promises -- instead of
    rebuilding a reason from a NaN (stats code review 2026-09-27 #2, findings 4 and 6)."""
    con.execute(
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at, statement, alpha_method) VALUES "
        "('dates','judge-a','v1',0.8,0.7,0.9,60,0.667,'accepted','2026-09-27 08:00:00+00',"
        "'what assess said','unit-bootstrap-percentile, 5 of 400 undefined resamples excluded')"
    )
    out_dir = tmp_path / "out"
    emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    decision = json.loads((out_dir / "judge_agreement.json").read_text(encoding="utf-8"))[
        "decisions"
    ][0]
    assert decision["statement"] == "what assess said"
    assert decision["alpha_method"].endswith("5 of 400 undefined resamples excluded")


def _judge_agreement(con, tmp_path) -> dict:
    out_dir = tmp_path / "out"
    emit_all(con, out_dir, as_of=datetime(2026, 10, 14, tzinfo=UTC), analysis_seed=1)
    return json.loads((out_dir / "judge_agreement.json").read_text(encoding="utf-8"))


def test_each_published_decision_names_its_judge(con, tmp_path):
    insert = (
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at) VALUES "
        "('line_item_description',?,'v1',0.8,0.7,0.9,60,0.667,?,'2026-10-14 08:00:00+00')"
    )
    con.execute(insert, ["judge-b", "rejected"])
    con.execute(insert, ["judge-a", "accepted"])
    decisions = _judge_agreement(con, tmp_path)["decisions"]
    assert [(d["field_type"], d["judge_slot"], d["status"]) for d in decisions] == [
        ("line_item_description", "judge-a", "accepted"),
        ("line_item_description", "judge-b", "rejected"),
    ]


def _judge_verdict(con, verdict_id, output_id, judge_slot, reason):
    correct = reason.startswith("judge majority EQUIVALENT")
    con.execute(
        "INSERT INTO verdicts VALUES (?,?,'line_1_description',?,'1','v1',?,?,now())",
        [verdict_id, output_id, f"judge:{judge_slot}", correct, reason],
    )


def test_inconclusive_counts_are_published_per_slot_and_judge(con, tmp_path):
    """The verdicts whose reason starts "judge inconclusive: " score incorrect; publishing how
    many there are, out of how many judge verdicts, lets a reader see how much of a slot's
    judged score is the judge failing to decide rather than the model being wrong."""
    seed(con, "pub1", "public", "1.00", "hash-1")
    seed(con, "pub2", "public", "2.00", "hash-2")
    con.execute(
        "INSERT INTO runs VALUES ('r-b',now(),NULL,'slot-b','ref','prov',false,'s1','sha','h')"
    )
    con.execute(
        "INSERT INTO outputs VALUES ('o-b1','r-b','pub1',1,'{}','call','prov',NULL,10,'ph',"
        "now(),NULL)"
    )
    inconclusive = "judge inconclusive: no majority in 3 samples"
    _judge_verdict(con, "j1", "o-pub1", "judge-a", inconclusive)
    _judge_verdict(con, "j2", "o-pub2", "judge-a", "judge majority EQUIVALENT (3 of 3)")
    _judge_verdict(con, "j3", "o-b1", "judge-b", "judge majority NOT_EQUIVALENT (2 of 3)")
    # A different field of the same output, so the count is per verdict, not per output.
    con.execute(
        "INSERT INTO verdicts VALUES ('j4','o-pub2','line_2_description','judge:judge-a','1',"
        "'v1',false,?,now())",
        [inconclusive],
    )

    assert _judge_agreement(con, tmp_path)["inconclusive"] == [
        {"slot": "slot-a", "judge_slot": "judge-a", "count": 2, "n": 3},
        {"slot": "slot-b", "judge_slot": "judge-b", "count": 0, "n": 1},
    ]


def test_no_judge_verdicts_publish_an_empty_inconclusive_list(con, tmp_path):
    seed(con, "pub1", "public", "1.00", "hash-1")  # a deterministic verdict only
    assert _judge_agreement(con, tmp_path)["inconclusive"] == []


def test_undefined_alpha_without_a_stored_statement_does_not_invent_a_reason(con, tmp_path):
    """A row written before the statement column existed has a NaN alpha and no stored reason.
    The publisher must not guess one ("every unit got the same verdict") from the NaN alone:
    any future path to a NaN would be published with that false reason (finding 6)."""
    con.execute(
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at) VALUES "
        "('money','judge-a','v1','NaN'::DOUBLE,'NaN'::DOUBLE,'NaN'::DOUBLE,60,0.667,'rejected',"
        "'2026-09-27 08:00:00+00')"
    )
    out_dir = tmp_path / "out"
    emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    decision = json.loads((out_dir / "judge_agreement.json").read_text(encoding="utf-8"))[
        "decisions"
    ][0]
    assert "same verdict" not in decision["statement"]
    assert (
        "undefined" in decision["statement"] and "reason was not recorded" in decision["statement"]
    )
    assert "n=60" in decision["statement"]


def test_a_failed_publish_leaves_the_output_directory_untouched(con, tmp_path, monkeypatch):
    """`write_json` refuses NaN mid-way through `emit_all`; before, the files already written
    stayed behind, mixing new and stale artifacts that the reproducibility check then reads
    (stats code review 2026-09-27 #2, finding 9)."""
    from ground_truth.publish import artifacts  # noqa: PLC0415

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "leaderboard.json").write_text("previous release", encoding="utf-8")
    original = artifacts.write_json

    def fail_on_regression(path: Path, body: dict[str, object]) -> None:
        if path.name == "regression.json":
            raise ValueError("Out of range float values are not JSON compliant")
        original(path, body)

    monkeypatch.setattr(artifacts, "write_json", fail_on_regression)
    with pytest.raises(ValueError):
        emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    assert sorted(p.name for p in out_dir.iterdir()) == ["leaderboard.json"]
    assert (out_dir / "leaderboard.json").read_text(encoding="utf-8") == "previous release"
    leftovers = [p.name for p in tmp_path.iterdir() if "staging" in p.name]
    assert leftovers == [], "no staging directory left behind"


def _previous_release(out_dir: Path) -> dict[str, bytes]:
    out_dir.mkdir()
    (out_dir / "leaderboard.json").write_text("previous leaderboard", encoding="utf-8")
    (out_dir / "calibration.json").write_text("previous calibration", encoding="utf-8")
    # Committed beside the emitted files but written by `triage.export_example`, not emit_all.
    (out_dir / "triage_example.json").write_text("triage", encoding="utf-8")
    return {p.name: p.read_bytes() for p in out_dir.iterdir()}


def _fail_replacing(monkeypatch, out_dir: Path, *, rollback_too: bool) -> None:
    """Make moving the staged release onto `out_dir` fail -- a file held open on Windows --
    and, with `rollback_too`, moving the previous release back as well."""
    import os  # noqa: PLC0415

    real_replace = os.replace

    def replace(src, dst):  # type: ignore[no-untyped-def]
        src, dst = Path(src), Path(dst)
        from_staging = any("-staging-" in part for part in src.parts)
        if dst == out_dir and (from_staging or rollback_too):
            raise PermissionError(f"file in use by another process: {src.name}")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)


def _leftovers(tmp_path: Path) -> list[str]:
    return [p.name for p in tmp_path.iterdir() if p.name.startswith(".out")]


def test_a_failure_moving_the_new_release_in_leaves_the_output_directory_as_it_was(
    con, tmp_path, monkeypatch
):
    """Code review 2026-09-28 #4: staged files were moved in one at a time, so a move failing
    partway (on Windows, a dev server or antivirus holding one file open) left old and new
    files mixed."""
    out_dir = tmp_path / "out"
    before = _previous_release(out_dir)
    _fail_replacing(monkeypatch, out_dir, rollback_too=False)
    with pytest.raises(PermissionError):
        emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    assert {p.name: p.read_bytes() for p in out_dir.iterdir()} == before
    assert _leftovers(tmp_path) == [], "no staging or backup left behind"


def test_a_failed_rollback_says_where_the_previous_release_is(con, tmp_path, monkeypatch):
    """Re-review 2026-09-28: if the lock that failed the swap also fails the rollback,
    `out_dir` is gone. The error must name the backup holding the previous release -- and
    stay the original exception type, so a caller retrying on PermissionError still can."""
    out_dir = tmp_path / "out"
    before = _previous_release(out_dir)
    _fail_replacing(monkeypatch, out_dir, rollback_too=True)
    with pytest.raises(PermissionError, match="staging") as excinfo:
        emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    backups = [p for p in tmp_path.iterdir() if p.name.startswith(".out-previous-")]
    assert len(backups) == 1
    notes = " ".join(getattr(excinfo.value, "__notes__", []))
    assert "previous release" in notes and str(backups[0]) in notes
    assert {p.name: p.read_bytes() for p in backups[0].iterdir()} == before


def test_the_file_another_emitter_writes_there_survives_a_publish(con, tmp_path):
    out_dir = tmp_path / "out"
    _previous_release(out_dir)
    emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    assert (out_dir / "triage_example.json").read_text(encoding="utf-8") == "triage"
    assert (out_dir / "leaderboard.json").read_text(encoding="utf-8") != "previous leaderboard"
    assert _leftovers(tmp_path) == [], "no staging or backup left behind"


@pytest.mark.parametrize("stray", ["client_triage.html", "results.duckdb"])
def test_publishing_over_unrecognised_files_refuses_and_touches_nothing(con, tmp_path, stray):
    """Re-review 2026-09-28: the swap replaces the whole folder, so an unrecognised file was
    either republished (a stray triage output -- the 2026-08-29 leak class) or, once only named
    files were carried over, silently deleted (`--out data` would take results.duckdb with it).
    Refusing, and naming the files, is the only outcome that neither leaks nor loses data."""
    out_dir = tmp_path / "out"
    before = _previous_release(out_dir)
    (out_dir / stray).write_text("not emit_all's", encoding="utf-8")
    before[stray] = (out_dir / stray).read_bytes()
    with pytest.raises(ValueError, match=stray):
        emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    assert {p.name: p.read_bytes() for p in out_dir.iterdir()} == before
    assert _leftovers(tmp_path) == [], "no staging or backup left behind"


@pytest.mark.parametrize(
    ("path", "ignored"),
    [
        (".artifacts-previous-abc12345/leaderboard.json", True),
        (".artifacts-staging-k9_x2m7q/leaderboard.json", True),
        (".data-previous-a1b2c3d4/results.duckdb", True),
        ("tests/fixtures/.config-previous-v1/settings.json", False),
    ],
)
def test_a_publish_backup_left_behind_is_never_committed(path, ignored):
    """Deleting the backup can fail on Windows after a successful swap; a leftover copy of the
    previous release must not be picked up by `git add`, whatever `--out` was named -- and the
    pattern matches only mkdtemp's 8-character suffix, not any hidden `-previous-` folder."""
    repo = Path(__file__).resolve().parents[2]
    if not (repo / ".git").exists():
        pytest.skip("not a git checkout (release tarball); nothing can be committed")
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=repo, check=False)
    assert (result.returncode == 0) is ignored, path


def test_a_committed_regression_watch_result_survives_a_publish(con, tmp_path):
    """Re-review 2026-09-28 (predates this branch, since 5ada687): regression.json is written
    by the local regression sweep and committed by hand; emit_all overwrote it with an empty
    stub, so a publish wiped real findings from the site."""
    out_dir = tmp_path / "out"
    _previous_release(out_dir)
    (out_dir / "regression.json").write_text('{"alerts": ["real"]}', encoding="utf-8")
    emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    assert (out_dir / "regression.json").read_text(encoding="utf-8") == '{"alerts": ["real"]}'


def test_a_regression_stub_is_written_only_when_no_result_is_committed(con, tmp_path):
    out_dir = tmp_path / "out"
    emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    assert json.loads((out_dir / "regression.json").read_text(encoding="utf-8"))["alerts"] == []


@pytest.mark.parametrize("name", [".gitkeep", ".DS_Store"])
def test_folder_metadata_neither_blocks_a_publish_nor_is_lost(con, tmp_path, name):
    out_dir = tmp_path / "out"
    _previous_release(out_dir)
    (out_dir / name).write_text("", encoding="utf-8")
    emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    assert (out_dir / name).exists()


def test_a_non_file_under_a_carried_name_is_refused_not_deleted(con, tmp_path):
    """The refusal and the carry-over apply one predicate: a directory named like a carried
    file passed the check, was not copied, and the swap deleted it."""
    out_dir = tmp_path / "out"
    _previous_release(out_dir)
    (out_dir / "triage_example.json").unlink()
    (out_dir / "triage_example.json").mkdir()
    (out_dir / "triage_example.json" / "inner.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="triage_example.json"):
        emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    assert (out_dir / "triage_example.json" / "inner.txt").read_text(encoding="utf-8") == "keep"


def test_unrecognised_files_are_refused_before_the_analysis_runs(con, tmp_path, monkeypatch):
    """The emitted names are static, so a stray file fails fast instead of after the whole
    private-split analysis has run."""
    from ground_truth.publish import artifacts  # noqa: PLC0415

    def analysis_must_not_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("the analysis ran before the folder was checked")

    monkeypatch.setattr(artifacts, "_emit_into", analysis_must_not_run)
    out_dir = tmp_path / "out"
    _previous_release(out_dir)
    (out_dir / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="stray.txt"):
        emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)


def test_the_declared_emitted_names_are_exactly_what_a_publish_writes(con, tmp_path):
    from ground_truth.publish import artifacts  # noqa: PLC0415

    out_dir = tmp_path / "out"
    written = emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    assert {p.name for p in written} == set(artifacts.EMITTED)


def test_an_interrupt_after_the_swap_succeeded_leaves_the_new_release_and_no_false_note(
    con, tmp_path, monkeypatch
):
    """Re-review 2026-09-28: an interrupt landing just after the rename into place was handled
    as a failed swap; the rollback then failed and the note told the operator to overwrite a
    good new release with the backup."""
    import os  # noqa: PLC0415

    out_dir = tmp_path / "out"
    _previous_release(out_dir)
    real_replace = os.replace

    def replace_then_interrupt(src, dst):  # type: ignore[no-untyped-def]
        real_replace(src, dst)
        if Path(dst) == out_dir and "-staging-" in Path(src).name:
            raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", replace_then_interrupt)
    with pytest.raises(KeyboardInterrupt) as excinfo:
        emit_all(con, out_dir, as_of=datetime(2026, 9, 27, tzinfo=UTC), analysis_seed=1)
    assert not getattr(excinfo.value, "__notes__", [])
    assert (out_dir / "leaderboard.json").read_text(encoding="utf-8") != "previous leaderboard"
    assert (out_dir / "triage_example.json").read_text(encoding="utf-8") == "triage"


def test_write_json_refuses_to_emit_nan(tmp_path):
    with pytest.raises(ValueError):
        write_json(tmp_path / "x.json", {"alpha": float("nan")})


def _reject_non_json_constant(token: str) -> None:
    raise AssertionError(f"published JSON contains the non-JSON token {token}")


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
