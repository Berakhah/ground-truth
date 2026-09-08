from ground_truth.triage.export_example import build_rows

# One runnable check on the demo-generation logic itself (the composition of load_intents /
# evaluate / find_flip_point into a JSON-ready row) -- not a re-test of those already-tested
# functions, and not a check on the hand-authored docs/triage-example.csv content beyond what
# the web E2E suite (web/e2e/triage.spec.ts) already requires of the page it feeds.


def test_docs_example_produces_one_row_per_intent():
    rows = build_rows()
    assert len(rows) == 4  # noqa: PLR2004 -- matches docs/triage-example.csv's row count


def test_every_row_carries_a_recommendation_and_rationale():
    for row in build_rows():
        assert row["ev"]["recommendation"]
        assert row["ev"]["rationale"]


def test_the_example_spans_automate_route_and_never_automate():
    recs = {row["ev"]["recommendation"] for row in build_rows()}
    assert {"automate", "never_automate", "route_to_human"} <= recs


def test_a_bounded_intents_flip_point_states_the_crossing_cost():
    bounded = [row for row in build_rows() if row["cost_of_error"] != "unbounded"]
    assert any("costs more than" in row["flip"]["sentence"] for row in bounded)


def test_the_unbounded_intent_never_flips():
    unbounded = [row for row in build_rows() if row["cost_of_error"] == "unbounded"]
    assert unbounded
    assert all("does not flip" in row["flip"]["sentence"] for row in unbounded)
