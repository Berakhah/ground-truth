from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CORRECTIONS = REPO / "docs" / "corrections.md"
TEMPLATE = REPO / ".github" / "ISSUE_TEMPLATE" / "right-of-reply.yml"
README = REPO / "README.md"
CHANGELOG = REPO / "CHANGELOG.md"
METHODOLOGY = REPO / "docs" / "methodology.md"


def test_right_of_reply_template_exists_and_is_labelled():
    assert "right-of-reply" in TEMPLATE.read_text(encoding="utf-8")


def test_response_windows_are_stated():
    body = CORRECTIONS.read_text(encoding="utf-8")
    assert "5 business days" in body and "15 business days" in body


def test_advance_notice_rule_is_stated():
    body = CORRECTIONS.read_text(encoding="utf-8")
    assert "10 business days" in body
    assert "regression" in body.lower() or "drift" in body.lower()


def test_three_outcomes_are_named():
    body = CORRECTIONS.read_text(encoding="utf-8").lower()
    for outcome in ("correction", "clarification", "no change"):
        assert outcome in body


def test_no_silent_edit_rule_is_stated():
    assert "never silently" in CHANGELOG.read_text(encoding="utf-8").lower()


def test_judge_wiring_entry_matches_the_shipped_headline_rules():
    """Final review 2026-10-14, I3: an unassessed judge is kept out of the headline (its
    verdicts are still published), the zero-sweeps claim names the database and the date as the
    analysis plan does, and the two final-review rulings are recorded."""
    text = " ".join(CHANGELOG.read_text(encoding="utf-8").split())
    assert "A judge with no decision is not scored in the headline" in text
    assert "on `data/results.duckdb` returned 0 on 2026-10-14" in text
    assert "weighted by the number of schema-valid graded outputs" in text
    assert "every slot's currently assigned judge" in text


def test_rerun_offer_is_stated():
    body = CORRECTIONS.read_text(encoding="utf-8").lower()
    assert "re-run" in body and "side by side" in body


def test_no_characterisation_of_vendor_honesty():
    """Measured claims only. Scan published prose for accusatory vocabulary."""
    banned = ("dishonest", "misleading", "fabricated", "lying", "deceptive", "fraudulent")
    for path in (README, CORRECTIONS, METHODOLOGY):
        lowered = path.read_text(encoding="utf-8").lower()
        for word in banned:
            assert word not in lowered, f"{path.name} characterises a vendor: {word!r}"


def test_readme_carries_a_scope_statement_early():
    head = " ".join(README.read_text(encoding="utf-8").split()[:200]).lower()
    assert "pay application" in head or "invoice" in head
    assert "field extraction" in head
