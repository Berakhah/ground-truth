"""Phase 2 Task 34: O'Brien-Fleming boundary as specified, and its two null tests."""
import math, random
from statistics import NormalDist
N = NormalDist()

K = 13
ALPHA = 0.05

def plan_boundary(look, total=K, alpha=ALPHA):
    """Exactly as Phase 2 Task 34 Step 3 specifies it."""
    t = look / total
    return N.inv_cdf(1 - alpha / 2) / math.sqrt(t)

print("Boundaries as the plan specifies them (C = z_a/2 = 1.959964):")
for k in range(1, K + 1):
    print(f"   look {k:2d}/13  t={k/K:.4f}  boundary={plan_boundary(k):.4f}")

print()
print("-" * 72)
print("A. test_sequential_controls_type_i_under_null, EXACTLY as written")
print("   (13 INDEPENDENT gauss(0,1) draws per trial, assert rate <= 0.06)")
print("-" * 72)
# analytic, since the draws are independent
p_no_reject = 1.0
for k in range(1, K + 1):
    ak = 2 * N.cdf(-plan_boundary(k))
    p_no_reject *= (1 - ak)
print(f"   analytic family-wise rejection rate = {1 - p_no_reject:.4f}")
rng = random.Random(0)
trials = 20000
rej = sum(any(abs(rng.gauss(0,1)) > plan_boundary(k) for k in range(1, K+1))
          for _ in range(trials))
print(f"   monte-carlo (n={trials})            = {rej/trials:.4f}")
print(f"   plan asserts rate <= 0.06           -> {'PASS' if rej/trials<=0.06 else 'FAIL'}")

print()
print("-" * 72)
print("B. test_fixed_threshold_inflates_alpha, EXACTLY as written")
print("   (13 INDEPENDENT draws vs fixed 1.96; plan says publish this number)")
print("-" * 72)
rng = random.Random(0)
rej = sum(any(abs(rng.gauss(0,1)) > 1.96 for _ in range(K)) for _ in range(trials))
print(f"   analytic  = {1 - 0.95**K:.4f}")
print(f"   simulated = {rej/trials:.4f}   plan asserts > 0.20 -> "
      f"{'PASS' if rej/trials>0.20 else 'FAIL'}")

print()
print("-" * 72)
print("C. What the REAL processes give (correlated Brownian monitoring,")
print("   corr(Z_j,Z_k) = sqrt(t_j/t_k) -- i.e. actual sequential looks)")
print("-" * 72)
def brownian_z(rng, K):
    """Z_k = B(t_k)/sqrt(t_k) with equally spaced information."""
    b = 0.0; out = []
    for k in range(1, K + 1):
        b += rng.gauss(0, math.sqrt(1.0 / K))
        out.append(b / math.sqrt(k / K))
    return out

trials = 200000
rng = random.Random(7)
rej_plan = rej_fixed = 0
for _ in range(trials):
    z = brownian_z(rng, K)
    if any(abs(z[k-1]) > plan_boundary(k) for k in range(1, K+1)): rej_plan += 1
    if any(abs(v) > 1.96 for v in z): rej_fixed += 1
print(f"   plan's boundary, true type-I error  = {rej_plan/trials:.4f}   (nominal 0.05)")
print(f"   naive fixed 1.96, true type-I error = {rej_fixed/trials:.4f}")
print(f"   -> plan would PUBLISH {rej/trials:.3f} where the truth is ~{rej_fixed/trials:.3f}")

print()
print("-" * 72)
print("D. The O'Brien-Fleming constant that ACTUALLY controls alpha at 13 looks")
print("-" * 72)
def type_i(C, trials=200000, seed=11):
    rng = random.Random(seed); hit = 0
    for _ in range(trials):
        z = brownian_z(rng, K)
        if any(abs(z[k-1]) > C / math.sqrt(k / K) for k in range(1, K+1)): hit += 1
    return hit / trials
lo, hi = 1.9, 2.6
for _ in range(14):
    mid = (lo + hi) / 2
    if type_i(mid, trials=60000) > ALPHA: lo = mid
    else: hi = mid
C = (lo + hi) / 2
print(f"   calibrated C_OBF(13 looks) ~= {C:.4f}   (plan uses 1.9600)")
print(f"   verified type-I at that C   = {type_i(C, trials=200000):.4f}")
print(f"   final-look boundary at that C = {C:.4f}  (plan's test allows 1.96 +/- 0.15 "
      f"-> {'still passes' if abs(C-1.96)<=0.15 else 'FAILS'})")

print()
print("-" * 72)
print("E. Lan-DeMets OBF alpha-spending function (the correct closed form)")
print("   alpha(t) = 2*(1 - Phi(z_{a/2}/sqrt(t)))   -- one line, no simulation")
print("-" * 72)
for k in (1, 4, 7, 10, 13):
    t = k / K
    print(f"   look {k:2d}  t={t:.4f}  cumulative alpha spent = "
          f"{2*(1-N.cdf(N.inv_cdf(1-ALPHA/2)/math.sqrt(t))):.6f}")
