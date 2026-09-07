"""Version-fingerprint observation across a sweep.

`04` B6: say a slot's served version cannot be pinned rather than implying it can. A model
that never returns a fingerprint is `NOT_EXPOSED`, not silently treated as stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import duckdb


class FingerprintStatus(StrEnum):
    STABLE = "STABLE"
    CHANGED = "CHANGED"
    NOT_EXPOSED = "NOT_EXPOSED"


@dataclass(frozen=True)
class SlotFingerprint:
    slot: str
    status: FingerprintStatus
    values: list[str]
    first_seen: datetime
    last_seen: datetime
    statement: str


def observe_fingerprints(con: duckdb.DuckDBPyConnection, sweep_id: str) -> list[SlotFingerprint]:
    rows = con.execute(
        "SELECT r.model_slot, o.fingerprint, o.observed_at "
        "FROM outputs o JOIN runs r ON r.run_id = o.run_id "
        "WHERE r.sweep_id = ?",
        [sweep_id],
    ).fetchall()

    by_slot: dict[str, list[tuple[str | None, datetime]]] = {}
    for slot, fingerprint, observed_at in rows:
        by_slot.setdefault(slot, []).append((fingerprint, observed_at))

    results: list[SlotFingerprint] = []
    for slot in sorted(by_slot):
        entries = by_slot[slot]
        first_seen = min(observed_at for _, observed_at in entries)
        last_seen = max(observed_at for _, observed_at in entries)
        values = sorted({fp for fp, _ in entries if fp is not None})
        has_null = any(fp is None for fp, _ in entries)

        status: FingerprintStatus
        statement: str
        if not values:
            status = FingerprintStatus.NOT_EXPOSED
            statement = (
                f"{slot} does not expose a version fingerprint. We cannot pin the served "
                f"version and do not claim to; results are attributed to the slot as served "
                f"between {first_seen:%Y-%m-%d} and {last_seen:%Y-%m-%d}."
            )
        elif len(values) == 1 and not has_null:
            status = FingerprintStatus.STABLE
            statement = (
                f"{slot} reported a single fingerprint {values[0]!r} across the sweep "
                f"({first_seen:%Y-%m-%d} to {last_seen:%Y-%m-%d})."
            )
        else:
            status = FingerprintStatus.CHANGED
            statement = (
                f"{slot} reported more than one fingerprint across the sweep: "
                f"{', '.join(values)}. Results from this slot span more than one served "
                f"version."
            )

        results.append(
            SlotFingerprint(
                slot=slot,
                status=status,
                values=values,
                first_seen=first_seen,
                last_seen=last_seen,
                statement=statement,
            )
        )

    return results
