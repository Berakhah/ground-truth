"""Tests for the nightly live smoke test harness (security baseline Task 52 item 8)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ground_truth.providers import SlotSpec
from ground_truth.regression.smoke import format_issue_body, main, run_smoke


def _slot(name: str) -> SlotSpec:
    return SlotSpec(
        slot=name,
        family="synthetic-family",
        provider="synthetic-provider",
        model_ref="synthetic-model-ref",
        trains_on_data=False,
        commercial_use=True,
        exposes_fingerprint=False,
        list_price_in_per_1m=Decimal("0"),
        list_price_out_per_1m=Decimal("0"),
        pricing_url="https://example.invalid/pricing",
        retrieved_at=date(2026, 1, 1),
    )


def test_run_smoke_reports_success_for_every_answering_slot() -> None:
    slots = {"a": _slot("a"), "b": _slot("b")}
    outcomes = run_smoke(slots, ping=lambda slot: f"pong from {slot.slot}")
    assert {o.slot: o.ok for o in outcomes} == {"a": True, "b": True}
    assert {o.slot: o.detail for o in outcomes} == {
        "a": "pong from a",
        "b": "pong from b",
    }


def test_run_smoke_records_a_raised_exception_as_a_failure_not_a_skip() -> None:
    """A smoke test that swallows a provider exception reports green with nothing behind
    it -- exactly the failure mode this harness exists to avoid."""

    def flaky_ping(slot: SlotSpec) -> str:
        if slot.slot == "broken":
            raise RuntimeError("connection reset")
        return "ok"

    slots = {"broken": _slot("broken"), "fine": _slot("fine")}
    outcomes = run_smoke(slots, ping=flaky_ping)
    by_slot = {o.slot: o for o in outcomes}
    assert by_slot["broken"].ok is False
    assert "connection reset" in by_slot["broken"].detail
    assert by_slot["fine"].ok is True


def test_run_smoke_visits_every_slot_even_after_a_failure() -> None:
    """One slot failing must never short-circuit the rest -- that would silently stop
    checking every slot after the alphabetically-first failure."""
    calls: list[str] = []

    def ping(slot: SlotSpec) -> str:
        calls.append(slot.slot)
        if slot.slot == "a":
            raise RuntimeError("boom")
        return "ok"

    slots = {name: _slot(name) for name in ("a", "b", "c")}
    run_smoke(slots, ping=ping)
    assert calls == ["a", "b", "c"]


def test_format_issue_body_names_every_failing_slot_and_its_detail() -> None:
    slots = {"a": _slot("a")}
    outcomes = run_smoke(slots, ping=lambda slot: (_ for _ in ()).throw(RuntimeError("gone")))
    body = format_issue_body(outcomes)
    assert "`a`" in body
    assert "gone" in body


@pytest.mark.parametrize("expected_exit_code", [0])
def test_main_exits_zero_and_states_the_gap_honestly(
    capsys: pytest.CaptureFixture[str], expected_exit_code: int
) -> None:
    """Phase 1 has no live gateway call implemented (ground_truth/_bok_shim.py). Until it
    does, `main()` must say so and exit 0 (matching regression-watch.yml's own
    no-op-until-ready pattern) rather than fabricate a smoke result or crash the nightly
    workflow with nobody watching it in real time."""
    exit_code = main()
    captured = capsys.readouterr()
    assert exit_code == expected_exit_code
    assert "no live provider gateway is implemented yet" in captured.out
