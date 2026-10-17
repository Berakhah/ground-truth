"""python -m ground_truth.simulate [--out data/simulated] [--seed 1]

A simulated sweep, so every screen has something to show while no provider keys exist.

It is the real pipeline with a simulated provider: `execute_sweep`, `run_judging`,
`grade_stored_outputs`, the judge-agreement assessment and `emit_all` all run unchanged. Only the
two things a provider supplies are invented -- a model's answer to a document and a judge's
answer to a pair of descriptions -- and what is right is decided by the real graders (a test
grades every value this module renders). Nothing here measures any model.

Everything it writes goes under one folder (default `data/simulated`, gitignored) next to a
`SIMULATED.txt` marker, and `run_simulation` refuses to write inside the repo's published
`artifacts/` folder. Its items are generated, not copied: the real private split is never read.
Slot names start `sim-`, the prices in its models file are invented, and any cost figure in its
artifacts is an invented number, never a price.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

from ground_truth._bok_shim import CallContext, Handle, Labelled, Response
from ground_truth.golden.build import _insert_items
from ground_truth.golden.generate import generate
from ground_truth.golden.rubric import freeze_rubric, loaded_rubric
from ground_truth.golden.schema import FieldType, Item, ItemField, Split
from ground_truth.grade import grade_stored_outputs
from ground_truth.graders.judge.aggregate import Sample, majority_vote
from ground_truth.graders.judge.agreement import assess, record_decision
from ground_truth.graders.judge.targets import select_judge_targets
from ground_truth.judge_runner import run_judging
from ground_truth.providers import judge_assignments
from ground_truth.publish.artifacts import emit_all
from ground_truth.runner import build_prompt, execute_sweep
from ground_truth.store.db import connect, migrate

REPO = Path(__file__).resolve().parents[1]
SIM_MARKER = "SIMULATED.txt"
DEFAULT_OUT = REPO / "data" / "simulated"
_PUBLISHED = REPO / "artifacts"
_RUBRIC_PATH = REPO / "docs" / "rubric.md"
_HUMAN_LABEL_BUDGET = 60  # judged units a simulated human labels per judge
_HUMAN_ERROR = 0.03  # how often that human labels a unit wrongly
_MIN_SAMPLES = 3  # judge samples a unit needs before it has a majority
# How often a correct answer is written in another form the rubric accepts, per field type.
_VARIANT_MONEY = 0.3
_VARIANT_DATE = 0.3
_VARIANT_IDENTIFIER = 0.2
_VARIANT_PARTY = 0.2
_PARAPHRASED = 0.3  # of correct descriptions, how many are reworded rather than copied
_FENCED = 0.2  # of outputs, how many are wrapped in a ```json fence
_COIN = 0.5


class SimulationRefused(RuntimeError):
    """The output folder is the published `artifacts/` folder or inside it."""


@dataclass(frozen=True)
class Profile:
    """How a simulated model behaves. `accuracy` is the chance a field is rendered correctly."""

    family: str
    accuracy: dict[FieldType, float]
    parse_failure: float  # an output that is not a usable JSON object at all
    latency_median_ms: int
    list_price_in_per_1m: str  # invented; never a real price
    list_price_out_per_1m: str


def _acc(*values: float) -> dict[FieldType, float]:
    order = (
        FieldType.MONEY,
        FieldType.PERCENT,
        FieldType.DATE,
        FieldType.IDENTIFIER,
        FieldType.PARTY_NAME,
        FieldType.ENUM_CATEGORY,
        FieldType.COUNT,
        FieldType.LINE_ITEM_DESCRIPTION,
    )
    return dict(zip(order, values, strict=True))


PROFILES: dict[str, Profile] = {
    "sim-small": Profile(
        "SIM-FAMILY-1",
        _acc(0.84, 0.88, 0.78, 0.82, 0.80, 0.88, 0.80, 0.70),
        0.05,
        450,
        "0.05",
        "0.20",
    ),
    "sim-medium": Profile(
        "SIM-FAMILY-2",
        _acc(0.93, 0.95, 0.90, 0.92, 0.90, 0.94, 0.92, 0.85),
        0.02,
        900,
        "0.30",
        "1.20",
    ),
    "sim-large": Profile(
        "SIM-FAMILY-3",
        _acc(0.97, 0.98, 0.96, 0.97, 0.95, 0.98, 0.97, 0.90),
        0.01,
        2200,
        "2.50",
        "10.00",
    ),
}
# model slot -> judge slot. Each judge's family differs from the model it judges (rule 4).
JUDGE_OF = {"sim-small": "sim-judge-a", "sim-medium": "sim-judge-b", "sim-large": "sim-judge-a"}
JUDGE_FAMILY = {"sim-judge-a": "SIM-JUDGE-FAMILY-1", "sim-judge-b": "SIM-JUDGE-FAMILY-2"}


# -- what a value looks like, right and wrong -----------------------------------------------

_TRADES = ("Concrete", "Glazing", "Masonry", "Roofing", "Plumbing", "Electrical", "Joinery")
_NAME_HEADS = ("Northern", "Apex", "Meridian", "Harbour", "Summit", "Keystone", "Atlas")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DESCRIPTION = re.compile(r"^(?P<trade>\w+) works, phase (?P<phase>\d+)$")


def render_value(field: ItemField, rng: random.Random) -> str:
    """The field as a model that read it correctly might write it: sometimes in another format
    the rubric accepts. The tests grade every rendering with the real graders."""
    value = field.expected_value
    match field.field_type:
        case FieldType.MONEY if rng.random() < _VARIANT_MONEY:
            return f"${Decimal(value):,.2f}"
        case FieldType.DATE if rng.random() < _VARIANT_DATE and _ISO_DATE.match(value):
            day = date.fromisoformat(value)
            return f"{day:%B} {day.day}, {day.year}"
        case FieldType.IDENTIFIER if rng.random() < _VARIANT_IDENTIFIER:
            return value.lower()
        case FieldType.PARTY_NAME if rng.random() < _VARIANT_PARTY:
            return value.upper()
        case _:
            return value


def _other_digit(char: str, rng: random.Random) -> str:
    return rng.choice([d for d in "0123456789" if d != char])


def corrupt_value(  # noqa: PLR0911 -- one return per field type
    field: ItemField, rng: random.Random, *, categories: list[str]
) -> str:
    """A wrong value of the right shape, always one the real graders mark incorrect."""
    value = field.expected_value
    match field.field_type:
        case FieldType.MONEY:
            shift = Decimal(rng.randint(10, 5000)) + Decimal(rng.randint(0, 99)) / 100
            return f"{Decimal(value) + shift:.2f}"
        case FieldType.PERCENT:
            return f"{Decimal(value) + Decimal(rng.choice(['2.5', '5.0', '7.5'])):.2f}"
        case FieldType.DATE:
            if not _ISO_DATE.match(value):
                return "2026-09-15"  # the document's date is a deliberately ambiguous trap
            days = rng.choice([-1, 1]) * rng.randint(1, 30)
            return (date.fromisoformat(value) + timedelta(days=days)).isoformat()
        case FieldType.IDENTIFIER:
            digits = [i for i, c in enumerate(value) if c.isdigit()]
            if not digits:
                return value + "X"
            at = rng.choice(digits)
            return value[:at] + _other_digit(value[at], rng) + value[at + 1 :]
        case FieldType.PARTY_NAME:
            head, _, rest = value.partition(" ")
            return f"{rng.choice([h for h in _NAME_HEADS if h != head])} {rest}".strip()
        case FieldType.ENUM_CATEGORY:
            return rng.choice([c for c in categories if c != value] or [value + "-x"])
        case FieldType.COUNT:
            count = int(value)
            return str(count + 1 if count < 1 or rng.random() < _COIN else count - 1)
        case FieldType.LINE_ITEM_DESCRIPTION:
            match = _DESCRIPTION.match(value)
            if match is None:
                return value + " (revised scope)"
            trade = rng.choice([t for t in _TRADES if t != match["trade"]])
            return f"{trade} works, phase {match['phase']}"


def paraphrase(value: str) -> str:
    """The same work in other words: what the judge is there to recognise as equivalent."""
    match = _DESCRIPTION.match(value)
    if match is None:
        return value + "."
    return f"Phase {match['phase']}: {match['trade'].lower()} works"


# -- the simulated provider -----------------------------------------------------------------

_JUDGE_PROMPT = re.compile(r"Text A:\n(?P<a>.*?)\n\nText B:\n(?P<b>.*?)\n\nReply", re.DOTALL)


class SimulatedProviders:
    """`resolve` and `call` with the shapes `execute_sweep` and `run_judging` expect."""

    def __init__(self, items: list[Item], *, seed: int, judge_accuracy: dict[str, float]) -> None:
        self._documents = {build_prompt(item).value: item for item in items}
        if len(self._documents) != len(items):
            raise ValueError("two items render the same document; the simulator keys on it")
        self._categories: dict[str, list[str]] = {}
        for item in items:
            for f in item.fields:
                if f.field_type is FieldType.ENUM_CATEGORY:
                    names = self._categories.setdefault(f.field_name, [])
                    if f.expected_value not in names:
                        names.append(f.expected_value)
        self._model_rng = random.Random(f"model:{seed}")
        self._judge_rng = random.Random(f"judge:{seed}")
        self._judge_accuracy = judge_accuracy
        self.paraphrases: set[str] = set()
        self._calls = 0

    def resolve(self, slot: str) -> Handle:
        return Handle(slot=slot, provider="simulated", model_ref=f"SIMULATED-{slot}")

    def is_equivalent(self, expected: str, observed: str) -> bool:
        return observed == expected or observed in self.paraphrases

    def call(
        self, handle: Handle, payload: Labelled[str], context: CallContext, **_: object
    ) -> Response:
        self._calls += 1
        if handle.slot in JUDGE_FAMILY:
            text, latency = self._judge(handle.slot, payload.value)
        else:
            text, latency = self._model(handle.slot, payload.value)
        return Response(
            text=text,
            ledger_call_id=f"sim-{self._calls}",
            provider_served="simulated",
            fingerprint=None,
            latency_ms=latency,
            tokens=(len(payload.value) + len(text)) // 4,
        )

    def _model(self, slot: str, document: str) -> tuple[str, int]:
        profile, rng = PROFILES[slot], self._model_rng
        item = self._documents[document]
        latency = max(1, round(rng.lognormvariate(math.log(profile.latency_median_ms), 0.35)))
        if rng.random() < profile.parse_failure:
            broken = rng.choice(["I could not read this document.", '{"application_no": "APP-'])
            return broken, latency
        out: dict[str, str] = {}
        for f in item.fields:
            if rng.random() < profile.accuracy[f.field_type]:
                if f.field_type is FieldType.LINE_ITEM_DESCRIPTION and rng.random() < _PARAPHRASED:
                    out[f.field_name] = paraphrase(f.expected_value)
                    self.paraphrases.add(out[f.field_name])
                else:
                    out[f.field_name] = render_value(f, rng)
            else:
                out[f.field_name] = corrupt_value(
                    f, rng, categories=self._categories.get(f.field_name, [])
                )
        body = json.dumps(out)
        return (f"```json\n{body}\n```" if rng.random() < _FENCED else body), latency

    def _judge(self, judge_slot: str, prompt: str) -> tuple[str, int]:
        rng = self._judge_rng
        match = _JUDGE_PROMPT.search(prompt)
        if match is None:
            raise ValueError("a judge call whose prompt has no two texts")
        a, b = match["a"], match["b"]
        truth = a == b or a in self.paraphrases or b in self.paraphrases
        said = truth if rng.random() < self._judge_accuracy[judge_slot] else not truth
        return ("EQUIVALENT" if said else "NOT_EQUIVALENT"), round(rng.uniform(300, 900))


# -- the run --------------------------------------------------------------------------------


def _price_lines(indent: str, price_in: str, price_out: str) -> list[str]:
    return [
        f"{indent}trains_on_data: false",
        f"{indent}commercial_use: true",
        f"{indent}exposes_fingerprint: false",
        f'{indent}list_price_in_per_1m: "{price_in}"',
        f'{indent}list_price_out_per_1m: "{price_out}"',
        f'{indent}pricing_url: "simulated:invented-not-a-price"',
        f'{indent}retrieved_at: "2026-10-17"',
    ]


def _models_yaml() -> str:
    lines = [
        "# SIMULATED. Every value is invented: no provider, no model, no price is real.",
        "slots:",
    ]
    for slot, p in PROFILES.items():
        lines += [
            f"  {slot}:",
            f'    family: "{p.family}"',
            '    provider: "simulated"',
            f'    model_ref: "SIMULATED-{slot}"',
            *_price_lines("    ", p.list_price_in_per_1m, p.list_price_out_per_1m),
            f"    judge: {JUDGE_OF[slot]}",
        ]
    lines.append("judge_slots:")
    for judge, family in JUDGE_FAMILY.items():
        lines += [
            f"  {judge}:",
            f'    family: "{family}"',
            '    provider: "simulated"',
            f'    model_ref: "SIMULATED-{judge}"',
            *_price_lines("    ", "1.00", "2.00"),
        ]
    return "\n".join(lines) + "\n"


def _record_judge_decisions(
    con: duckdb.DuckDBPyConnection,
    sim: SimulatedProviders,
    items: list[Item],
    assignments: dict[str, str],
    *,
    seed: int,
) -> None:
    """A simulated human labels up to `_HUMAN_LABEL_BUDGET` judged units per judge (wrongly
    `_HUMAN_ERROR` of the time); `assess` then measures agreement exactly as it would for real
    labels, and the decision is recorded for `matrix.build` to gate on."""
    declared = {(i.item_id, f.field_name): f for i in items for f in i.fields}
    rng = random.Random(f"human:{seed}")
    field_type = FieldType.LINE_ITEM_DESCRIPTION
    names = sorted({n for (_, n), f in declared.items() if f.field_type is field_type})
    for judge in sorted(set(assignments.values())):
        units = [
            (name, t)
            for name in names
            for t in select_judge_targets(con, name)
            if assignments.get(t.model_slot) == judge
            and t.observed is not None
            and (t.item_id, name) in declared
        ]
        rng.shuffle(units)
        judge_verdicts: dict[str, str] = {}
        human_verdicts: dict[str, str] = {}
        samples: list[Sample] = []
        for name, target in units[:_HUMAN_LABEL_BUDGET]:
            observed = target.observed
            if observed is None:
                continue
            rows = con.execute(
                "SELECT presentation_order, raw_judgement FROM judge_samples "
                "WHERE output_id = ? AND field_name = ? AND judge_slot = ? ORDER BY sample_id",
                [target.output_id, name, judge],
            ).fetchall()
            unit = [Sample(order, raw, len(observed)) for order, raw in rows]
            if len(unit) < _MIN_SAMPLES:
                continue
            equivalent = sim.is_equivalent(
                declared[(target.item_id, name)].expected_value, observed
            )
            if rng.random() < _HUMAN_ERROR:
                equivalent = not equivalent
            judge_verdicts[target.output_id] = majority_vote(unit).value
            human_verdicts[target.output_id] = "EQUIVALENT" if equivalent else "NOT_EQUIVALENT"
            samples += unit
        if judge_verdicts:
            report = assess(field_type.value, judge_verdicts, human_verdicts, samples, seed=seed)
            record_decision(con, report, rubric_version="v1", judge_slot=judge)


@dataclass(frozen=True)
class SimulationResult:
    out_dir: Path
    n_outputs: int
    distinct_replicate_sets: int


def _count(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = con.execute(sql).fetchone()
    return 0 if row is None else int(row[0])


def run_simulation(
    out_dir: Path,
    *,
    seed: int = 1,
    n_items: int = 300,
    replicates: int = 5,
    judge_b_accuracy: float = 0.93,
) -> SimulationResult:
    resolved = out_dir.resolve()
    if resolved == _PUBLISHED.resolve() or _PUBLISHED.resolve() in resolved.parents:
        raise SimulationRefused(
            f"{out_dir} is the published artifacts folder or inside it; simulated results "
            "must never be written where a release could publish them."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "simulated.duckdb"
    for stale in (db_path, out_dir / "simulated.duckdb.wal"):
        stale.unlink(missing_ok=True)
    models_path = out_dir / "models.yaml"
    models_path.write_text(_models_yaml(), encoding="utf-8")
    (out_dir / SIM_MARKER).write_text(
        "SIMULATED. Every number in this folder comes from a simulated provider, not from any "
        "model. Slot names start `sim-`; the prices are invented. Never publish it, never "
        "quote it, never copy it into artifacts/.\n",
        encoding="utf-8",
    )

    n_public = round(n_items * 0.4)
    items = [
        item.model_copy(update={"split": Split.PUBLIC if n < n_public else Split.PRIVATE})
        for n, item in enumerate(generate(n_items, f"sim-{seed}", "v1", salt=f"sim-salt-{seed}"))
    ]
    sim = SimulatedProviders(
        items, seed=seed, judge_accuracy={"sim-judge-a": 0.96, "sim-judge-b": judge_b_accuracy}
    )
    rubric = loaded_rubric(_RUBRIC_PATH)
    con = connect(db_path)
    try:
        migrate(con)
        freeze_rubric(con, _RUBRIC_PATH, "v1")
        _insert_items(con, items, "simulated")
        execute_sweep(
            con,
            items,
            list(PROFILES),
            replicates,
            context=CallContext(),
            resolve_fn=sim.resolve,
            call_fn=sim.call,
            models_yaml=models_path,
            allow_dirty=True,
        )
        assignments = judge_assignments(models_path)
        run_judging(
            con,
            items,
            rubric,
            n=3,
            resolve_fn=sim.resolve,
            call_fn=sim.call,
            context=CallContext(),
            models_yaml=models_path,
        )
        grade_stored_outputs(con, items, rubric, judges=assignments)
        _record_judge_decisions(con, sim, items, assignments, seed=seed)
        emit_all(
            con,
            out_dir / "artifacts",
            as_of=datetime(2026, 10, 17, tzinfo=UTC),
            analysis_seed=seed,
            models_yaml=models_path,
        )
        n_outputs = _count(con, "SELECT count(*) FROM outputs")
        distinct = _count(
            con,
            "SELECT count(*) FROM (SELECT o.item_id, r.model_slot FROM outputs o "
            "JOIN runs r ON r.run_id = o.run_id GROUP BY 1, 2 "
            "HAVING count(DISTINCT o.raw_output) > 1)",
        )
    finally:
        con.close()
    return SimulationResult(out_dir, n_outputs, distinct)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a simulated sweep (no provider is called).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--items", type=int, default=300)
    parser.add_argument("--replicates", type=int, default=5)
    parser.add_argument(
        "--judge-b-accuracy",
        type=float,
        default=0.93,
        help="how often judge B answers correctly; lower it to see a weak judge rejected",
    )
    args = parser.parse_args()
    result = run_simulation(
        args.out,
        seed=args.seed,
        n_items=args.items,
        replicates=args.replicates,
        judge_b_accuracy=args.judge_b_accuracy,
    )
    print(f"SIMULATED sweep: {result.n_outputs} outputs -> {result.out_dir}")


if __name__ == "__main__":
    main()
