from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict

from ground_truth.stats.bootstrap import Interval
from ground_truth.stats.mde import describe_mde
from ground_truth.triage.expected_value import EVResult, evaluate
from ground_truth.triage.ingest import Intent, load_intents
from ground_truth.triage.sensitivity import FlipPoint, find_flip_point

TEMPLATE_DIR = Path(__file__).parent / "templates"

# describe_mde's discordance_rate == 0.0 is rejected (mde_paired_binary requires it in (0, 1]).
# A floor of 1% keeps the caveat renderable for a legitimately perfect-or-near-perfect
# accuracy.point without ever reading as a claim about the true error rate -- see
# _mde_caveat below for the full reasoning.
_MIN_DISCORDANCE_RATE = 0.01


class ReportRow(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    intent: Intent
    ev: EVResult
    flip: FlipPoint
    accuracy: Interval


def _money(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _mde_caveat(accuracy: Interval) -> str:
    # describe_mde() is built for a paired two-model comparison (n_items, discordance_rate from
    # McNemar's test on matched items) -- see ground_truth.stats.mde. A triage report row is a
    # single intent's automate/route-to-human decision, not a model-vs-model comparison, so
    # there is no "true" discordance_rate available from ReportRow/Intent/EVResult/Interval.
    # Inventing an arbitrary constant here would be exactly the fabricated-number problem this
    # project's CLAUDE.md forbids for cost figures, extended to statistics.
    #
    # Instead we repurpose the call as an honest "what a sample this size could and couldn't
    # detect" caveat, using only real data already on this row: n_items=accuracy.n (the actual
    # sample size behind the accuracy interval) and discordance_rate approximated as this row's
    # own measured error rate, 1 - accuracy.point -- the closest available, non-fabricated proxy
    # for "how often this process disagrees with the correct answer".
    #
    # Edge case: a perfect or near-perfect accuracy.point (accuracy.point == 1.0 is a
    # legitimate, non-fabricated result, not an unrealistic one) drives 1 - accuracy.point to
    # 0.0, which mde_paired_binary rejects outright. A small positive floor keeps the renderer
    # from crashing on exactly the row that earned the best score, without asserting anything
    # about the true discordance rate -- it is a numerical floor, not a measurement.
    discordance_rate = max(1.0 - accuracy.point, _MIN_DISCORDANCE_RATE)
    return describe_mde(accuracy.n, discordance_rate)


def _row_context(row: ReportRow) -> dict[str, object]:
    intent, ev, flip, accuracy = row.intent, row.ev, row.flip, row.accuracy
    cost_of_error = (
        "unbounded" if intent.unbounded_error else _money(intent.cost_of_error or Decimal(0))
    )
    return {
        "name": intent.intent,
        "volume_per_month": intent.volume_per_month,
        "current_cost_per_item": _money(intent.current_cost_per_item),
        "cost_of_error": cost_of_error,
        "client_quote": intent.client_quote,
        "accuracy_point": f"{accuracy.point:.3f}",
        "accuracy_low": f"{accuracy.low:.3f}",
        "accuracy_high": f"{accuracy.high:.3f}",
        "accuracy_n": accuracy.n,
        "ev_low": _money(ev.ev_low),
        "ev_point": _money(ev.ev_point),
        "ev_high": _money(ev.ev_high),
        "recommendation": ev.recommendation.value.replace("_", " "),
        "rationale": ev.rationale,
        "flip_sentence": flip.sentence,
        "mde_caveat": _mde_caveat(accuracy),
    }


def render_report(rows: list[ReportRow], *, generated_at: datetime, methodology_url: str) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.html.j2")
    # Read at render time (not module import time) and inject as a <style> block -- never a
    # <link> -- so the returned HTML is fully self-contained for emailing and printing.
    css = (TEMPLATE_DIR / "report.css").read_text(encoding="utf-8")
    return template.render(
        generated_at=generated_at,
        methodology_url=methodology_url,
        rows=[_row_context(row) for row in rows],
        css=css,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the print-ready triage report.")
    parser.add_argument("--intake", required=True, type=Path, help="Path to the intake CSV.")
    parser.add_argument("--out", required=True, type=Path, help="Path to write the HTML report.")
    parser.add_argument("--methodology-url", required=True, help="Link to the methodology page.")
    args = parser.parse_args()

    intents = load_intents(args.intake)

    # PLACEHOLDER: this project does not yet have real sweep-execution wired up to produce a
    # measured accuracy Interval per intent (that lands in a later phase). In the same spirit
    # as Task 2's models.yaml placeholder scaffold, the CLI path below uses one illustrative,
    # clearly-labelled placeholder Interval and automation cost so this command produces a real,
    # readable report today. Nothing here is a measured result. Swap this for a real per-intent
    # accuracy Interval (from ground_truth.stats.bootstrap, run against real grader output)
    # once that pipeline exists. render_report() itself takes real ReportRows built from real
    # measurements -- this placeholder is only about where the CLI gets its accuracy input.
    placeholder_accuracy = Interval(
        point=0.90, low=0.85, high=0.94, n=50, method="placeholder-not-measured"
    )
    placeholder_automation_cost_per_item = Decimal("0.10")
    placeholder_ceiling = Decimal("1000")

    rows = [
        ReportRow(
            intent=intent,
            ev=evaluate(intent, placeholder_accuracy, placeholder_automation_cost_per_item),
            flip=find_flip_point(
                intent,
                placeholder_accuracy,
                placeholder_automation_cost_per_item,
                ceiling=placeholder_ceiling,
            ),
            accuracy=placeholder_accuracy,
        )
        for intent in intents
    ]

    html = render_report(rows, generated_at=datetime.now(UTC), methodology_url=args.methodology_url)
    args.out.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
