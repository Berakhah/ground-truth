"""One lightweight self-check for `publish/methodology.py` -- this module has zero coverage
in the plan's own test suite (it only imports from `publish.leaderboard`), so this confirms
the render actually converts Markdown, injects supplied live figures, and renders an honest
placeholder for every figure that was not supplied -- never silently dropping it."""

from pathlib import Path

from ground_truth.publish.methodology import NOT_YET_MEASURED, render_methodology_html

METHODOLOGY = Path(__file__).resolve().parents[2] / "docs" / "methodology.md"


def test_render_methodology_html_converts_body_and_handles_live_figures():
    html = render_methodology_html(
        METHODOLOGY,
        current_n=180,
        mde_statement="MDE sentence for the current sweep.",
        intra_rater_statement=None,
        judge_agreement_statements=["field-x: alpha=0.90 [0.85, 0.94], n=50"],
        fingerprint_statements=None,
    )

    # A recognisable fragment of the converted Markdown body survived conversion -- the
    # "## Scope" heading this task added becomes a real <h2>, not literal markdown text.
    assert "<h2>Scope</h2>" in html

    # Every supplied live figure appears verbatim.
    assert "180" in html
    assert "MDE sentence for the current sweep." in html
    assert "field-x: alpha=0.90 [0.85, 0.94], n=50" in html

    # Every omitted figure renders the honest placeholder -- never vanishes silently.
    assert html.count(NOT_YET_MEASURED) == 2  # noqa: PLR2004 -- intra-rater statement + fingerprints


def test_render_methodology_html_all_figures_omitted_are_all_placeholders():
    html = render_methodology_html(METHODOLOGY)
    assert html.count(NOT_YET_MEASURED) == 5  # noqa: PLR2004 -- one per live-figure slot
