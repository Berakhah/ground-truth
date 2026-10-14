from __future__ import annotations

from dataclasses import dataclass

import duckdb

from ground_truth.graders.deterministic.schema import extract_fields


@dataclass(frozen=True)
class JudgeTarget:
    item_id: str
    model_slot: str
    output_id: str
    observed: str | None  # None: the field is modally absent, so there is nothing to judge


def _observed(raw_output: str, field_name: str) -> str | None:
    try:
        value = extract_fields(raw_output).get(field_name)
    except ValueError:
        return None  # unparseable: schema grading already marks it; here it votes as absent
    return None if value is None else str(value)


def select_judge_targets(con: duckdb.DuckDBPyConnection, field_name: str) -> list[JudgeTarget]:
    """One output per (item, slot): the replicate holding the modal value of `field_name`.

    Audit H8 / spec section 15: judging every replicate costs 300 x 6 x 5 x 3 = 27,000 calls;
    judging the modal output costs 5,400 and loses nothing, since replicate variance is
    already measured by the deterministic graders and the calibration signal. A tie goes to
    the value first seen in replicate order, and the target is the lowest replicate holding
    it, so the same outputs always select the same target.
    """
    rows = con.execute(
        "SELECT o.item_id, r.model_slot, o.output_id, o.raw_output FROM outputs o "
        "JOIN runs r ON r.run_id = o.run_id ORDER BY o.item_id, r.model_slot, o.replicate_idx"
    ).fetchall()
    groups: dict[tuple[str, str], list[tuple[str, str | None]]] = {}
    for item_id, slot, output_id, raw in rows:
        groups.setdefault((item_id, slot), []).append((output_id, _observed(raw, field_name)))
    targets = []
    for (item_id, slot), replicates in groups.items():
        values = [value for _, value in replicates]
        modal = max(dict.fromkeys(values), key=values.count)  # max keeps the first of a tie
        output_id = next(oid for oid, value in replicates if value == modal)
        targets.append(JudgeTarget(item_id, slot, output_id, modal))
    return targets
