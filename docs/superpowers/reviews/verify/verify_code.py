"""Replicate the plans' code verbatim and probe it."""
import re, hashlib
from decimal import Decimal, DecimalException, localcontext

print("="*72); print("5. parse_decimal (Phase 1 Task 11) on inputs the plan never tests")
print("="*72)
_STRIP = re.compile(r"[^\d,.\-()%]"); _VALID = re.compile(r"^-?\d+(\.\d+)?$")
def parse_decimal(raw):
    text = _STRIP.sub("", raw.strip())
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    percent = text.endswith("%"); text = text.rstrip("%")
    if "," in text and "." in text:
        text = (text.replace(",", "") if text.rindex(".") > text.rindex(",")
                else text.replace(".", "").replace(",", "."))
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = f"{head}.{tail}" if len(tail) in (1, 2) else text.replace(",", "")
    if not _VALID.match(text): raise ValueError(f"unparseable: {raw!r}")
    with localcontext() as ctx:
        ctx.prec = 28; value = Decimal(text)
    if percent: value = value / Decimal(100)
    if negative: value = -value
    return value + Decimal(0)

for raw in ['1234.56 EUR', 'approximately 1234.56', 'about 40', '1e5',
            'USD 1,234.56 (revised)', 'n/a', '1234.56 or 1234.57', '$0']:
    try: print(f"   {raw!r:32} -> {parse_decimal(raw)}")
    except ValueError as e: print(f"   {raw!r:32} -> ValueError (rejected)")
print("   NOTE: currency/unit tokens are stripped, so '1234.56 EUR' grades")
print("         EQUAL to an expected USD 1234.56, and prose parses as a number.")

print(); print("="*72)
print("6. parse_judgement (Phase 2 Task 25) on prose the plan never tests")
print("="*72)
def parse_judgement(raw):
    t = raw.strip().upper()
    if "NOT_EQUIVALENT" in t: return "NOT_EQUIVALENT"
    if "EQUIVALENT" in t: return "EQUIVALENT"
    return "INCONCLUSIVE"
for raw in ["NOT_EQUIVALENT", "not equivalent", "They are not equivalent.",
            "No, these are not equivalent", "NOT EQUIVALENT", "Not-equivalent"]:
    v = parse_judgement(raw)
    flag = "  <-- VERDICT INVERTED" if ("not" in raw.lower() and v == "EQUIVALENT") else ""
    print(f"   {raw!r:36} -> {v}{flag}")

print(); print("="*72)
print("7. find_flip_point / sweep arithmetic (Phase 1 Task 20)")
print("="*72)
VOL, CUR, AUTO = Decimal(1000), Decimal("2.00"), Decimal("0.10")
LO, HI = Decimal("0.905"), Decimal("0.935")
def rec(coe):
    saving = CUR - AUTO
    lo = VOL * (LO*saving - (1-LO)*coe); hi = VOL * (HI*saving - (1-HI)*coe)
    if lo > 0: return "AUTOMATE"
    if hi < 0: return "ROUTE_TO_HUMAN"
    return "INSUFFICIENT_EVIDENCE"
ceiling, steps = Decimal(1000), 200
step = (ceiling / steps).quantize(Decimal("0.01"))
print(f"   grid step = {step}")
base = rec(Decimal(0)); flips_at = None
for i in range(steps + 1):
    c = (step * i).quantize(Decimal("0.01"))
    if rec(c) != base: flips_at = c; break
print(f"   from_rec={base}  flips_at={flips_at}  to_rec={rec(flips_at)}")
below, above = rec(flips_at - 1), rec(flips_at + 1)
print(f"   test probes flips_at-1 -> {below}")
print(f"   test probes flips_at+1 -> {above}")
print(f"   assert below != above  -> {'PASS' if below != above else 'FAIL'}")
print(f"   true boundary is at cost_of_error = {Decimal('1.7195')/Decimal('0.095'):.4f}")

print(); print("="*72)
print("8. item_id is a PREFIX of the published content_hash (Phase 1 Task 8)")
print("="*72)
ch = hashlib.sha256(b"42:0:line_1=45000.00").hexdigest()
item_id = ch[:16]
print(f"   content_hash (published in manifest) = {ch}")
print(f"   item_id      (must never be published) = {item_id}")
print(f"   item_id in content_hash ? {item_id in ch}")
print("   -> Phase 3 test_private_item_ids_never_appear_in_published_output")
print("      scans artifacts for item_id substrings; manifest_private.json and")
print("      verdicts_private_by_hash.jsonl both contain content_hash. ALWAYS FAILS.")

print(); print("="*72)
print("9. Call-budget arithmetic")
print("="*72)
print(f"   sweep (spec 15): 300 x 6 x 5              = {300*6*5:,}")
print(f"   judge as Task 24 writes it (per output, n=3) = {300*6*5*3:,}")
print(f"   TOTAL                                        = {300*6*5 + 300*6*5*3:,}")
print(f"   judge on modal output per (item,slot) x3     = {300*6*3:,}  (4.4x cheaper)")
