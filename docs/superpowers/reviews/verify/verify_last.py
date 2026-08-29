import math, random, hashlib
from statistics import NormalDist
N = NormalDist()
print("="*72); print("10. Degenerate interval at the boundary (Phase 1 Task 16)")
print("="*72)
print("   _interval() returns method='degenerate', low=high=point when std==0.")
print("   A slot scoring 180/180 on the private split therefore publishes:")
print("      accuracy 1.000 [1.000, 1.000]  n=180")
n = 180
# Clopper-Pearson one-sided lower bound at 95% for x=n successes: alpha^(1/n)
lower = 0.05 ** (1 / n)
print(f"   Correct 95% one-sided Clopper-Pearson lower bound = {lower:.4f}")
print(f"   Rule of three approximation  1 - 3/n              = {1-3/n:.4f}")
print(f"   -> the published interval understates uncertainty by "
      f"{(1-lower)*100:.2f} percentage points, at exactly the point a")
print("      leaderboard makes its strongest claim.")
print("   Same defect at 0/180 (a slot that always fails).")

print(); print("="*72)
print("11. Private-split derivability (Phase 1 Task 9 Step 5 + .env.example)")
print("="*72)
print("   .env.example (COMMITTED) ships GT_PUBLIC_SEED=42.")
print("   Task 9 Step 5: build.py 'generates 300 items, calls")
print("     assign_splits(items, public_n=120, seed=int(GT_PUBLIC_SEED))'")
print("   It never says which seed generates the 300. If GT_PUBLIC_SEED does,")
print("   then generate(300, 42, 'v1') + assign_splits(.., 120, 42) reconstructs")
print("   ALL 180 private items WITH LABELS from committed data alone.")
print()
print("   Even with a separate private seed: content_hash = sha256(f'{seed}:{n}:{payload}')")
print("   and generate.py is published (Apache-2.0, spec 13.1 'grader code').")
print("   The message space is fully enumerable, so the published manifest is a")
print("   commitment whose only strength is the SEED'S ENTROPY:")
for bits, label in [(8,"seed 1-255"), (16,"a year+id"), (32,"random int32"), (128,"secrets.token_hex(16)")]:
    print(f"      {label:24} {bits:3d} bits -> 2^{bits} generator runs to invert")
print("   A 32-bit seed is brute-forceable; the spec assumes secrecy, not entropy.")

print(); print("="*72)
print("12. pyproject addopts vs the plans' per-task verification commands")
print("="*72)
print("   [tool.pytest.ini_options] addopts = "
      "'--cov=ground_truth --cov-report=term-missing --cov-fail-under=75'")
print("   Applies to EVERY pytest invocation, including:")
for cmd in ["pytest tests/test_repo_hygiene.py -v   (Task 1 Step 7)",
            "pytest tests/store/test_db.py -v       (Task 3 Step 4)",
            "pytest tests/golden/test_schema.py -v  (Task 4 Step 4)"]:
    print(f"      uv run {cmd}")
print("   Each measures coverage over ALL of ground_truth/ from one test file,")
print("   scores far below 75, and EXITS NON-ZERO after the tests pass.")
print("   ~50 'Expected: PASS' steps across the three plans are unreachable.")
print()
print("   Also: markers declare 'slow' but addopts never deselects it, so")
print("   every full run pays the 1000/1000/2000-trial simulations.")
