"""Renders `docs/methodology.md` to HTML for the site, injecting the **live** figures this
project's other modules produce (current n, the MDE sentence, intra-rater disagreement, judge
agreement, fingerprint statements) instead of requiring anyone to hand-copy them into prose.
A methodology page whose numbers are typed by hand drifts away from the results it describes,
usually silently -- this module exists so that drift can't happen quietly.

Every live figure that is `None`/empty renders as an explicit "not yet measured" placeholder;
none is ever silently omitted. That is this project's publication rule for empty states,
applied here to the one page that is supposed to be the read-the-methodology destination.
"""

from __future__ import annotations

from pathlib import Path

import markdown

NOT_YET_MEASURED = "not yet measured"


def _statement_block(label: str, statements: list[str] | None) -> str:
    if not statements:
        return f"<p><strong>{label}:</strong> {NOT_YET_MEASURED}</p>"
    items = "".join(f"<li>{statement}</li>" for statement in statements)
    return f"<p><strong>{label}:</strong></p><ul>{items}</ul>"


def render_methodology_html(  # noqa: PLR0913 -- each optional figure is a distinct live number
    md_path: Path,
    *,
    current_n: int | None = None,
    mde_statement: str | None = None,
    intra_rater_statement: str | None = None,
    judge_agreement_statements: list[str] | None = None,
    fingerprint_statements: list[str] | None = None,
) -> str:
    body_html = markdown.markdown(md_path.read_text(encoding="utf-8"), extensions=["extra"])

    live_figures = "".join(
        [
            f"<p><strong>Current n:</strong> "
            f"{current_n if current_n is not None else NOT_YET_MEASURED}</p>",
            f"<p><strong>Minimum detectable effect:</strong> "
            f"{mde_statement or NOT_YET_MEASURED}</p>",
            f"<p><strong>Intra-rater disagreement:</strong> "
            f"{intra_rater_statement or NOT_YET_MEASURED}</p>",
            _statement_block("Judge agreement", judge_agreement_statements),
            _statement_block("Fingerprints", fingerprint_statements),
        ]
    )

    return f"{body_html}<section><h2>Live figures</h2>{live_figures}</section>"
