"""Verify the numeric claims embedded in the Ground Truth plans. Stdlib only."""
import math, random
from statistics import NormalDist
N = NormalDist()

print("=" * 72)
print("1. Krippendorff nominal alpha on the data in Phase 2 Task 26's test")
print("=" * 72)
obs_a = {"1":"1","2":"2","3":"3","4":"3","5":"2","6":"1","7":"4","8":"1","9":"2",
         "10":"1","11":"1","12":"3","13":"3","14":"4","15":"3"}
obs_b = {"1":"1","2":"2","3":"3","4":"3","5":"2","6":"2","7":"4","8":"1","9":"2",
         "10":"1","11":"1","12":"3","13":"3","14":"4","15":"4"}
ratings = {"obs_a": obs_a, "obs_b": obs_b}
units = {}
for rater, m in ratings.items():
    for u, v in m.items():
        units.setdefault(u, []).append(v)
coinc = {}
for u, vals in units.items():
    mu = len(vals)
    if mu < 2: continue
    for i, c in enumerate(vals):
        for j, k in enumerate(vals):
            if i == j: continue
            coinc[(c, k)] = coinc.get((c, k), 0) + 1.0 / (mu - 1)
n_total = sum(coinc.values())
marg = {}
for (c, k), v in coinc.items():
    marg[c] = marg.get(c, 0) + v
Do = sum(v for (c, k), v in coinc.items() if c != k)
sum_sq = sum(v * v for v in marg.values())
De = (n_total ** 2 - sum_sq) / (n_total - 1)
alpha = 1 - Do / De
print(f"  coincidence total n = {n_total}")
print(f"  marginals           = {dict(sorted(marg.items()))}")
print(f"  observed disagree   = {Do}")
print(f"  expected disagree   = {De:.6f}")
print(f"  ALPHA               = {alpha:.6f}")
print(f"  plan asserts        = 0.743 +/- 0.005  ->  {'PASS' if abs(alpha-0.743)<=0.005 else 'FAIL'}")

print()
print("=" * 72)
print("2. Cohen's kappa worked examples (Phase 2 Task 26)")
print("=" * 72)
def kappa(a, b):
    assert len(a) == len(b)
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    cats = set(a) | set(b)
    pe = sum((a.count(c)/n) * (b.count(c)/n) for c in cats)
    return (po - pe) / (1 - pe)
a1 = ["yes"]*25 + ["no"]*25
b1 = ["yes"]*20 + ["no"]*5 + ["yes"]*10 + ["no"]*15
print(f"  worked example kappa = {kappa(a1,b1):.6f}  (plan asserts 0.40)  "
      f"{'PASS' if abs(kappa(a1,b1)-0.40)<1e-9 else 'FAIL'}")
a2 = ["x"]*50 + ["y"]*50
b2 = (["x"]*25 + ["y"]*25) * 2
print(f"  independent  kappa   = {kappa(a2,b2):.6f}  (plan asserts 0.0)   "
      f"{'PASS' if abs(kappa(a2,b2))<0.02 else 'FAIL'}")

print()
print("=" * 72)
print("3. MDE closed form (Phase 1 Task 17)")
print("=" * 72)
def mde(n, disc, alpha=0.05, power=0.8, m=1):
    za = N.inv_cdf(1 - (alpha/m)/2); zb = N.inv_cdf(power)
    return (za + zb) * math.sqrt(disc / n)
v = mde(180, 0.10)
print(f"  mde(180,0.10) = {v:.8f}   plan asserts 0.066033 +/- 5e-5  "
      f"{'PASS' if abs(v-0.066033)<5e-5 else 'FAIL'}")
print(f"  monotone in n:      {mde(300,0.10) < mde(180,0.10)}")
print(f"  rises w/ m=48:      {mde(180,0.10,m=48) > mde(180,0.10)}  ({mde(180,0.10,m=48):.4f})")

print()
print("=" * 72)
print("4. Benjamini-Hochberg 1995 Table 1 (Phase 2 Task 28)")
print("=" * 72)
ps = [0.0001,0.0004,0.0019,0.0095,0.0201,0.0278,0.0298,0.0344,
      0.0459,0.3240,0.4262,0.5719,0.6528,0.7590,1.0000]
m = len(ps); fdr = 0.05
kmax = 0
for k, p in enumerate(sorted(ps), start=1):
    if p <= k / m * fdr: kmax = k
print(f"  rejections at FDR 0.05 = {kmax}   plan asserts 4   "
      f"{'PASS' if kmax==4 else 'FAIL'}")
