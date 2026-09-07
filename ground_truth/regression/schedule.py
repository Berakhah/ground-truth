"""The pre-registered quarterly look calendar for the regression watch.

Sequential testing (`stats/sequential.py`) only controls the type-I error of the 13-look
calendar it was calibrated for -- a look taken outside that calendar spends alpha the
analysis plan never budgeted for. `next_look`/`record_look` count looks per calendar quarter
against the `looks` table so a repeated or unscheduled look is caught rather than silently
run; `unscheduled_look_warning` is the sentence that makes an out-of-calendar look impossible
to publish without acknowledging it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import duckdb

from ground_truth.stats.sequential import LOOKS_PER_QUARTER


@dataclass(frozen=True)
class LookRecord:
    quarter: str
    look: int
    total_looks: int
    run_at: datetime


def next_look(con: duckdb.DuckDBPyConnection, now: datetime) -> LookRecord:
    """The next look due for `now`'s calendar quarter: `count(existing looks) + 1`."""
    quarter = f"{now.year}Q{(now.month - 1) // 3 + 1}"
    row = con.execute("SELECT count(*) FROM looks WHERE quarter = ?", [quarter]).fetchone()
    # SELECT count(*) always returns exactly one row; the assertion documents that
    # invariant for mypy's benefit, it never fires.
    assert row is not None
    count = int(row[0])
    return LookRecord(quarter=quarter, look=count + 1, total_looks=LOOKS_PER_QUARTER, run_at=now)


def record_look(con: duckdb.DuckDBPyConnection, record: LookRecord) -> None:
    """Insert the look. The `(quarter, look)` primary key raises on a repeat -- a silently
    repeated look would spend alpha twice without anyone noticing."""
    con.execute(
        "INSERT INTO looks VALUES (?, ?, ?, ?)",
        [record.quarter, record.look, record.total_looks, record.run_at],
    )


def unscheduled_look_warning(record: LookRecord) -> str | None:
    """`None` for a look within the pre-registered calendar; otherwise the notice that must
    accompany any result from it before publication."""
    if record.look <= record.total_looks:
        return None
    return (
        f"Look {record.look} exceeds the {record.total_looks} looks pre-registered for "
        f"{record.quarter}. This look spends alpha beyond the declared calendar and must be "
        f"recorded in the changelog before any result from it is published."
    )
