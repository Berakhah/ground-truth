import re
import subprocess
from dataclasses import dataclass
from dataclasses import field as dc_field
from types import SimpleNamespace

import pytest

from ground_truth import runner
from ground_truth._bok_shim import (
    CacheMode,
    CallContext,
    FailoverMode,
    Handle,
    Labelled,  # noqa: F401 -- imported to prove the shim's public surface, not directly used
    ProvidersUnavailable,
    Response,
    Sensitivity,
    SensitivityViolation,
)
from ground_truth.golden.generate import generate
from ground_truth.runner import build_prompt, execute_sweep
from ground_truth.store.db import connect, migrate


@dataclass
class FakeGateway:
    """Records exactly what the runner asked for, so the tests can assert the flags."""

    seen: list[tuple[str, CacheMode, FailoverMode, Sensitivity, bool]] = dc_field(
        default_factory=list
    )
    fallback_slots: frozenset[str] = frozenset()
    refuse_commercial: bool = False

    def resolve(self, lane: str) -> Handle:
        return Handle(
            slot=lane,
            provider="fake",
            model_ref="fake-ref-1",
            is_fallback=lane in self.fallback_slots,
        )

    def call(  # noqa: PLR0913 -- mirrors router.call's contract-shaped signature
        self,
        handle,
        payload,
        context,
        *,
        response_schema=None,
        tools_disabled=False,
        cache=CacheMode.ENABLED,
        failover=FailoverMode.ENABLED,
    ) -> Response:
        if self.refuse_commercial and context.commercial:
            raise SensitivityViolation(
                "provider 'fake' commercial_use is unverified; terms "
                "https://example.invalid/terms retrieved 2026-08-31"
            )
        self.seen.append((handle.slot, cache, failover, payload.sensitivity, context.commercial))
        return Response(
            text='{"contract_sum": "1.00"}',
            ledger_call_id=f"{handle.slot}-{len(self.seen)}",
            provider_served="fake",
            fingerprint=None,
            latency_ms=42,
        )


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def sweep(con, gw, items, slots, replicates, *, commercial=False):  # noqa: PLR0913
    return execute_sweep(
        con,
        items,
        slots,
        replicates,
        context=CallContext(commercial=commercial),
        resolve_fn=gw.resolve,
        call_fn=gw.call,
    )


def test_sweep_writes_one_output_per_item_slot_replicate(con):
    items = generate(count=4, seed=1, rubric_version="v1")
    sweep(con, FakeGateway(), items, ["slot-a", "slot-b"], 5)
    assert con.execute("SELECT count(*) FROM outputs").fetchone()[0] == 4 * 2 * 5


def test_sweep_never_writes_verdicts(con):
    items = generate(count=2, seed=1, rubric_version="v1")
    sweep(con, FakeGateway(), items, ["slot-a"], 3)
    assert con.execute("SELECT count(*) FROM verdicts").fetchone()[0] == 0


def test_benchmark_execution_bypasses_cache(con):
    gw = FakeGateway()
    sweep(con, gw, generate(count=2, seed=1, rubric_version="v1"), ["slot-a"], 5)
    assert gw.seen and all(cache is CacheMode.DISABLED for _, cache, _, _, _ in gw.seen), (
        "a cache hit would return identical text for replicates 2-5 and fabricate zero variance"
    )


def test_benchmark_slot_does_not_failover(con):
    """Model identity is the variable under study. A silent failover would attribute
    slot-a's output to slot-b's provider and corrupt the benchmark invisibly."""
    gw = FakeGateway()
    sweep(con, gw, generate(count=2, seed=1, rubric_version="v1"), ["slot-a"], 5)
    assert gw.seen and all(fo is FailoverMode.DISABLED for _, _, fo, _, _ in gw.seen)


def test_provider_failure_writes_no_row_rather_than_a_substituted_one(con):
    class Failing(FakeGateway):
        def call(self, *a, **k):
            raise ProvidersUnavailable("slot-a")

    items = generate(count=2, seed=1, rubric_version="v1")
    with pytest.raises(ProvidersUnavailable):
        sweep(con, Failing(), items, ["slot-a"], 5)
    assert con.execute("SELECT count(*) FROM outputs").fetchone()[0] == 0, (
        "a failed slot must leave a gap, never a row served by someone else"
    )


def test_fallback_handle_is_refused_for_benchmark_execution(con):
    """lanes.resolve returns a deterministic fallback handle when nothing is eligible.
    Recording its output as a model result would publish a non-result as a measurement."""
    gw = FakeGateway(fallback_slots=frozenset({"slot-a"}))
    with pytest.raises(ValueError, match="fallback"):
        sweep(con, gw, generate(count=1, seed=1, rubric_version="v1"), ["slot-a"], 1)


def test_payload_is_labelled_synthetic(con):
    gw = FakeGateway()
    sweep(con, gw, generate(count=1, seed=1, rubric_version="v1"), ["slot-a"], 1)
    assert all(sens is Sensitivity.SYNTHETIC for _, _, _, sens, _ in gw.seen)


def test_ledger_call_id_recorded_for_every_output(con):
    sweep(con, FakeGateway(), generate(count=2, seed=1, rubric_version="v1"), ["slot-a"], 2)
    missing = con.execute(
        "SELECT count(*) FROM outputs WHERE ledger_call_id IS NULL OR ledger_call_id = ''"
    ).fetchone()[0]
    assert missing == 0, "without a ledger id, fingerprint tracking is impossible"


def test_replicate_indices_start_at_one_and_are_contiguous(con):
    sweep(con, FakeGateway(), generate(count=1, seed=1, rubric_version="v1"), ["slot-a"], 5)
    rows = con.execute("SELECT replicate_idx FROM outputs ORDER BY replicate_idx").fetchall()
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5]


def test_commercial_run_refuses_non_commercial_provider(con):
    gw = FakeGateway(refuse_commercial=True)
    items = generate(count=1, seed=1, rubric_version="v1")
    with pytest.raises(SensitivityViolation, match="commercial_use"):
        sweep(con, gw, items, ["slot-a"], 1, commercial=True)


def test_refusal_message_cites_its_evidence(con):
    gw = FakeGateway(refuse_commercial=True)
    items = generate(count=1, seed=1, rubric_version="v1")
    with pytest.raises(SensitivityViolation) as exc:
        sweep(con, gw, items, ["slot-a"], 1, commercial=True)
    assert "https://" in str(exc.value) and "retrieved" in str(exc.value), (
        "a refusal a client's counsel cannot audit is not a control"
    )


def test_no_model_id_literal_in_runner_source():
    import inspect  # noqa: PLC0415

    from ground_truth import runner  # noqa: PLC0415

    lowered = inspect.getsource(runner).lower()
    for banned in ("gemini", "llama", "gpt-", "claude-", "mistral", "qwen"):
        assert banned not in lowered, f"model id {banned!r} must live in models.yaml, not source"


def test_prompt_contains_the_document_not_its_hash():
    item = generate(count=1, seed=1, rubric_version="v1")[0]
    payload = build_prompt(item)
    assert item.content_hash not in payload.value, "the hash is not the document"
    assert "PROGRESS BILLING SUMMARY" in payload.value
    assert len(payload.value) > 200, "a prompt this short cannot contain a document"  # noqa: PLR2004


def test_run_records_the_resolved_model_ref_not_a_placeholder(con):
    sweep(con, FakeGateway(), generate(count=1, seed=1, rubric_version="v1"), ["slot-a"], 1)
    ref = con.execute("SELECT resolved_model_ref FROM runs").fetchone()[0]
    assert ref and "runtime" not in ref and ref != "unknown"


def test_run_records_the_models_yaml_hash(con):
    sweep(con, FakeGateway(), generate(count=1, seed=1, rubric_version="v1"), ["slot-a"], 1)
    assert re.fullmatch(
        r"[0-9a-f]{64}", con.execute("SELECT models_yaml_hash FROM runs").fetchone()[0]
    )


def _dirty_git_run(cmd, **kwargs):
    """Fakes `git rev-parse HEAD` succeeding at 'abc123' with a dirty porcelain status."""
    stdout = "abc123\n" if cmd[1] == "rev-parse" else "M ground_truth/runner.py\n"
    return SimpleNamespace(stdout=stdout)


def test_code_version_raises_on_dirty_tree(monkeypatch):
    """audit H7: a sweep recorded against a dirty tree cannot be reproduced."""
    monkeypatch.setattr(runner.subprocess, "run", _dirty_git_run)
    with pytest.raises(RuntimeError, match="dirty"):
        runner._code_version(allow_dirty=False)


def test_code_version_allow_dirty_returns_dirty_suffixed_version(monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", _dirty_git_run)
    assert runner._code_version(allow_dirty=True) == "abc123-dirty"


def test_code_version_raises_when_git_command_fails(monkeypatch):
    """audit H7: the original swallowed this and returned 'unknown'. A sweep with no
    provenance is not a measurement, so this must raise instead."""

    def _failing_git_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd)

    monkeypatch.setattr(runner.subprocess, "run", _failing_git_run)
    with pytest.raises(RuntimeError):
        runner._code_version(allow_dirty=False)
