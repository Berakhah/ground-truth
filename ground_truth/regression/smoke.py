"""Nightly live smoke test harness (`00` B4 / `04` B6, security baseline Task 52 item 8).

Models get deleted or silently swapped behind a stable name without notice. A *weekly full
sweep* (the actual regression watch, see `ground_truth.regression.detect`) is not a smoke test
for that failure mode -- if quota for the week is already spent, or the sweep itself is broken,
the very first sign of a vanished model could be days late. This module is the harness for a
small, cheap, *daily* check: one call per configured slot, just enough to prove the slot still
answers, run from `.github/workflows/nightly-smoke.yml`.

It is deliberately decoupled from any concrete provider client: `run_smoke` takes a `ping`
callable and never imports a provider SDK itself (`00` R1 -- no hardcoded model names, and no
provider-specific code creeping into this module either). Phase 1 has no live gateway call
implemented at all (`ground_truth/_bok_shim.py`'s docstring names the bok-core symbols this
will eventually call through; none of `resolve`/`call` exist yet). Until that lands, `main()`
below says so honestly and exits 0 -- the same "nothing to check yet, succeed as a no-op"
pattern `.github/workflows/regression-watch.yml` already uses for `artifacts/regression.json`,
rather than fabricating a smoke result or crashing a scheduled workflow that nobody is
watching in real time.

Any test that ever *does* call a real ping function through here must wrap it in a `vcrpy`
cassette (`tests/cassettes/`, see the README there) so the recorded interaction replays
offline afterwards -- this project's test suite has zero live network dependence.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ground_truth.providers import SlotSpec


@dataclass(frozen=True)
class SmokeOutcome:
    slot: str
    ok: bool
    detail: str
    checked_at: datetime


def run_smoke(
    slots: dict[str, SlotSpec],
    ping: Callable[[SlotSpec], str],
) -> list[SmokeOutcome]:
    """Ping every configured slot once. A slot whose `ping` raises is recorded as failed,
    never skipped silently -- a nightly smoke test that swallows exceptions is worse than
    no smoke test, because it reports green with nothing behind it."""
    outcomes: list[SmokeOutcome] = []
    for name in sorted(slots):
        checked_at = datetime.now(UTC)
        try:
            detail = ping(slots[name])
        except Exception as exc:  # noqa: BLE001 -- any provider failure is a smoke failure
            outcomes.append(
                SmokeOutcome(slot=name, ok=False, detail=str(exc), checked_at=checked_at)
            )
        else:
            outcomes.append(SmokeOutcome(slot=name, ok=True, detail=detail, checked_at=checked_at))
    return outcomes


def format_issue_body(failures: list[SmokeOutcome]) -> str:
    lines = ["Nightly smoke test found slot(s) that did not answer:", ""]
    for outcome in failures:
        lines.append(f"- `{outcome.slot}` at {outcome.checked_at.isoformat()}: {outcome.detail}")
    lines.append("")
    lines.append(
        "This does not by itself confirm a model was removed or renamed -- see "
        "ground_truth.regression.fingerprint for that determination from a full sweep. "
        "This is the cheap daily trip-wire (00 B4 / 04 B6)."
    )
    return "\n".join(lines)


def main() -> int:
    # KNOWN GAP: no live gateway call is implemented yet (see this module's docstring) -- the
    # bok-core `resolve`/`call` symbols _bok_shim.py mirrors do not exist as callables here.
    # Left failing honestly by doing nothing and saying so, per this project's rule against
    # fabricated results, rather than faking a ping.
    print(
        "nightly-smoke: no live provider gateway is implemented yet (Phase 1 shim only, "
        "see ground_truth/_bok_shim.py) -- nothing to ping. This is a documented gap, not "
        "a fabricated pass."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
