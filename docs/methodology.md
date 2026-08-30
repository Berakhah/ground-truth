# Methodology decisions

## Synthetic corpus generator (Task 8)

`../ledger-sense/` was checked before writing `ground_truth/golden/generate.py`. As of
2026-08-30 its worktree (`phase-0-platform`) contains only auth/storage/API-stub code --
the extraction and generation phases have not started there, and a search for
pay-application/G702/G703/AIA/invoice generator code found only incidental comment
matches, no generator to wrap. The synthetic corpus generator is therefore implemented
locally in `ground_truth/golden/generate.py`, per this project's own design, rather than
wrapping a sibling-project component. No AIA form artifact is reproduced; the rendered
documents use this project's own layout and wording with equivalent column semantics
only.
