"""Minimum stand-in for bok-core, mirroring INTERFACE-CONTRACT.md v0.1 exactly.

ponytail: local shim, not the real substrate. Every symbol here has the same name and
signature as its bok_core counterpart, so replacing it is an import change and nothing
else -- `from bok_core.boundary.sensitivity import Labelled, Sensitivity, Trust`,
`from bok_core.boundary.policy import CallContext, SensitivityViolation`,
`from bok_core.gateway.lanes import resolve`, `from bok_core.gateway.router import
call, CacheMode, FailoverMode`. Deviating from those shapes here would mean porting
this twice. The foreign key outputs.ledger_call_id -> bok_ledger.call_id is the
load-bearing part; see contract section 3.4.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Sensitivity(StrEnum):
    PUBLIC = "PUBLIC"
    SYNTHETIC = "SYNTHETIC"
    REDACTED = "REDACTED"
    CLIENT_CONFIDENTIAL = "CLIENT_CONFIDENTIAL"


class Trust(StrEnum):
    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"


class SensitivityViolation(Exception):
    """Raised by router.call before dispatch. The message cites its evidence."""


class ProvidersUnavailable(RuntimeError):
    """No eligible provider served the call. Never substitute another slot's provider."""


@dataclass(frozen=True)
class Labelled(Generic[T]):  # noqa: UP046 -- mirrors bok_core's typing.Generic shape exactly
    value: T
    sensitivity: Sensitivity
    trust: Trust = Trust.TRUSTED


class CallContext(BaseModel):
    commercial: bool = False


class CacheMode(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class FailoverMode(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class Handle:
    slot: str
    provider: str
    model_ref: str = ""
    is_fallback: bool = False


@dataclass(frozen=True)
class Response:
    text: str
    ledger_call_id: str
    provider_served: str
    fingerprint: str | None
    latency_ms: int


class Quota(BaseModel):
    """Contract section 3.3. None means the provider does not publish that limit --
    the planner must treat it as unbounded, never as zero."""

    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None

    def __init__(
        self,
        rpm: int | None = None,
        tpm: int | None = None,
        rpd: int | None = None,
        **data: object,
    ) -> None:
        # bok_core's real Quota is documented positionally -- `Quota(rpm, tpm, rpd)`, contract
        # section 3.3 and INTERFACE-CONTRACT.md A5 -- but pydantic's BaseModel.__init__ is
        # keyword-only by default. This override is the minimal bridge to that shape: same
        # fields, same defaults, same validation, just constructible positionally too.
        super().__init__(rpm=rpm, tpm=tpm, rpd=rpd, **data)


def remaining(provider: str) -> Quota:  # pragma: no cover - shim stub
    """Public query, not only internal enforcement. Phase 2's scheduler asks before
    dispatching each sweep batch. The shim returns an unbounded quota."""
    return Quota()


_BLACKOUT = ContextVar("bok_blackout", default=False)
_BREACHES: list[str] = []


@contextmanager
def blackout() -> Iterator[None]:
    """Every lane raises ProvidersUnavailable. Defeats the response cache, the probe
    TTL cache, the fallback chain, and any local-fallback that is not deterministic."""
    token = _BLACKOUT.set(True)
    _BREACHES.clear()
    try:
        yield
    finally:
        _BLACKOUT.reset(token)


def assert_blackout_complete() -> None:
    """Asserts no code path reached a provider under blackout. THE shared test."""
    assert _BREACHES == [], f"code reached a provider under blackout: {_BREACHES}"
