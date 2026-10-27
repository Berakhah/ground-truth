"""Open GitHub issues for committed regression findings (called by regression-watch.yml).

Reads artifacts/regression.json, which a human generates locally and commits. Two rules the
old inline shell loop lacked:

* placeholder data (`"placeholder": true`) opens nothing -- it is demo output, not a finding;
* an issue is never opened twice: titles are compared with every existing issue (open or
  closed), and a regression title carries its look number so a later look is a new finding.

A finding naming a provider carries a 10-business-day notice before publication (spec 13.3).
This opens the issue and stops; publishing is a separate, manual step.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

NOTICE = (
    "Per spec section 13.3, a regression finding naming a provider carries a 10-business-day "
    "notice before publication. This issue is that notice. Do not publish this finding until "
    "the notice period has elapsed -- publishing is a separate, manual step."
)
_FINGERPRINT_STATUSES = {"CHANGED", "NOT_EXPOSED"}


def issues_to_open(doc: dict, existing_titles: set[str]) -> list[tuple[str, str]]:
    if doc.get("placeholder"):
        return []
    issues: list[tuple[str, str]] = []
    for alert in doc.get("alerts", []):
        if alert.get("detected") is not True:
            continue
        look = alert.get("look", doc.get("look"))
        title = f"Regression detected: {alert['slot']} / {alert['field_type']} (look {look})"
        issues.append((title, f"{alert['statement']}\n\n{NOTICE}\n"))
    for fp in doc.get("fingerprints", []):
        if fp.get("status") in _FINGERPRINT_STATUSES:
            issues.append((f"Fingerprint {fp['status']}: {fp['slot']}", fp["statement"]))
    return [(t, b) for t, b in issues if t not in existing_titles]


def _gh_list_titles() -> set[str]:
    out = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["gh", "issue", "list", "--state", "all", "--limit", "1000", "--json", "title"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {row["title"] for row in json.loads(out)}


def _gh_create_issue(title: str, body: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["gh", "issue", "create", "--title", title, "--body", body],  # noqa: S607
        check=True,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    list_titles: Callable[[], set[str]] = _gh_list_titles,
    create_issue: Callable[[str, str], object] = _gh_create_issue,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("artifacts/regression.json"))
    args = parser.parse_args(argv)

    if not args.file.is_file():
        print(f"No {args.file} committed yet -- nothing to check.")
        return 0
    doc = json.loads(args.file.read_text(encoding="utf-8"))
    if doc.get("placeholder"):
        print(f"{args.file} is placeholder data -- nothing to open.")
        return 0
    for title, body in issues_to_open(doc, list_titles()):
        create_issue(title, body)
        print(f"opened: {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
