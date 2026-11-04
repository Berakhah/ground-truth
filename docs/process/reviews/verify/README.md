# Audit verification scripts

Stdlib only. No dependencies, no network. Each script prints the plan's claim beside the
value re-derived from first principles, so every finding in
`../2026-08-29-ground-truth-audit.md` can be checked rather than trusted.

```bash
python verify_stats.py   # Krippendorff alpha, Cohen's kappa, MDE, Benjamini-Hochberg
python verify_seq.py     # O'Brien-Fleming boundary, both null simulations, C_OBF calibration
python verify_code.py    # parse_decimal, parse_judgement, flip point, item_id, call budget
python verify_last.py    # degenerate interval, seed entropy, the coverage gate
```

Runtimes are seconds except `verify_seq.py`, which simulates ~1.5M Brownian
trajectories and takes about a minute.
