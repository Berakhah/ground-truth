"""Generator for the web site's synthetic triage demo -- never a real engagement.

Real triage output is CLIENT_CONFIDENTIAL and goes to gitignored `deliverables/`, never to
`artifacts/` (see `ground_truth.publish.artifacts.emit_all`'s docstring). Task 47's plan is
explicit that the public `/triage` screen "renders a synthetic worked example
(docs/triage-example.csv), never a real engagement" -- this script builds that example by
composing the same, already-tested pipeline `ground_truth.triage.report.main()` wires
(`load_intents` -> `evaluate` -> `find_flip_point`), against the fictional intake CSV, and
writes the result as plain JSON for the Next.js page to statically import. Re-run it any time
`docs/triage-example.csv` changes; it is not part of any runtime request path.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.expected_value import evaluate
from ground_truth.triage.ingest import load_intents
from ground_truth.triage.sensitivity import find_flip_point

REPO_ROOT = Path(__file__).resolve().parents[2]
INTAKE_CSV = REPO_ROOT / "docs" / "triage-example.csv"
OUTPUT_JSON = REPO_ROOT / "artifacts" / "triage_example.json"

# Synthetic, clearly-placeholder accuracy: the same literals as leaderboard.json's demo-slot-a
# row, reused here for consistency rather than inventing a second unmeasured number. No
# per-intent accuracy pipeline exists yet -- the same gap triage.report.main()'s own
# PLACEHOLDER comment documents for the CLI path.
ACCURACY = Interval(point=0.92, low=0.87, high=0.96, n=180, method="cluster-BCa")
AUTOMATION_COST_PER_ITEM = Decimal("0.10")
CEILING = Decimal("1000")


def build_rows() -> list[dict[str, object]]:
    intents = load_intents(INTAKE_CSV)
    rows: list[dict[str, object]] = []
    for intent in intents:
        ev = evaluate(intent, ACCURACY, AUTOMATION_COST_PER_ITEM)
        flip = find_flip_point(intent, ACCURACY, AUTOMATION_COST_PER_ITEM, ceiling=CEILING)
        rows.append(
            {
                "intent": intent.intent,
                "volume_per_month": intent.volume_per_month,
                "current_cost_per_item": str(intent.current_cost_per_item),
                "cost_of_error": (
                    "unbounded" if intent.unbounded_error else str(intent.cost_of_error)
                ),
                "client_quote": intent.client_quote,
                "accuracy": ACCURACY.model_dump(),
                "ev": {
                    "recommendation": ev.recommendation.value,
                    "ev_low": str(ev.ev_low),
                    "ev_point": str(ev.ev_point),
                    "ev_high": str(ev.ev_high),
                    "n": ev.n,
                    "rationale": ev.rationale,
                },
                "flip": {
                    "sentence": flip.sentence,
                    "flips_at": str(flip.flips_at) if flip.flips_at is not None else None,
                },
            }
        )
    return rows


def main() -> None:
    rows = build_rows()
    assert rows, "docs/triage-example.csv produced zero rows"  # noqa: S101 -- generator script
    body = {
        "placeholder": True,
        "note": "Synthetic worked example -- never a real client engagement.",
        "rows": rows,
    }
    OUTPUT_JSON.write_text(json.dumps(body, sort_keys=True, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
