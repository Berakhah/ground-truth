// Loaders for a simulated run (python -m ground_truth.simulate), read from disk at render time.
//
// Only the `*-example` routes use these, and those 404 unless GT_E2E_FIXTURES=1 (see
// ./fixtures.ts), so a simulated number can reach the browser only on a developer's machine. The
// files live in data/simulated/ (gitignored), never in artifacts/. Server components only.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { JudgeAgreementPayload, LeaderboardPayload } from "@/lib/artifacts";

const DIR = join(process.cwd(), "..", "data", "simulated", "artifacts");

function readJson(name: string): Record<string, unknown> | null {
  try {
    return JSON.parse(readFileSync(join(DIR, name), "utf-8")) as Record<string, unknown>;
  } catch {
    return null;
  }
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isStr = (v: unknown): v is string => typeof v === "string";

function validInterval(v: unknown): boolean {
  return isObj(v) && isNum(v.point) && isNum(v.low) && isNum(v.high) && isNum(v.n);
}

// Only what the views read: a file that is not shaped like this is refused, not rendered as NaN.
function validRow(v: unknown): boolean {
  if (!isObj(v) || !isStr(v.slot) || !validInterval(v.accuracy)) return false;
  const { cost, latency, per_field: perField } = v;
  return (
    isObj(cost) && isStr(cost.value) && isStr(cost.unit) && isStr(cost.caveat) &&
    isObj(latency) && isNum(latency.p50) && isNum(latency.p95) && isStr(latency.caveat) &&
    isObj(perField) && Object.values(perField).every(validInterval)
  );
}

function validHeldBack(v: unknown): boolean {
  return v === undefined || (Array.isArray(v) && v.every((h) => isObj(h) && isStr(h.field_type) && isStr(h.reason)));
}

function validDecision(v: unknown): boolean {
  return (
    isObj(v) && isStr(v.field_type) && isNum(v.n_units) && isNum(v.threshold) &&
    (v.status === "accepted" || v.status === "rejected") &&
    (v.alpha === null || isNum(v.alpha))
  );
}

// null when there is no run, or when the run predates the fields the page reads. A stale run is
// refused rather than filled in: defaulting `distinguishability` to [] would print "All models
// are distinguishable" about intervals nobody compared.
export function loadSimulatedLeaderboard(): LeaderboardPayload | null {
  const raw = readJson("leaderboard.json");
  if (
    raw === null ||
    !Array.isArray(raw.rows) || !raw.rows.every(validRow) ||
    !Array.isArray(raw.distinguishability) || !raw.distinguishability.every(isStr) ||
    !validHeldBack(raw.held_back_field_types)
  ) {
    return null;
  }
  return {
    version: "simulated",
    as_of: String(raw.as_of ?? ""),
    // Fixed, not read from the file: a header link is not something a data file should choose.
    methodology_url: "/methodology",
    // The page's own placeholder banner says "no live measurement has run yet"; the route
    // shows a SIMULATED banner instead, so this stays false.
    placeholder: false,
    held_back_field_types: raw.held_back_field_types as LeaderboardPayload["held_back_field_types"],
    rows: raw.rows as LeaderboardPayload["rows"],
    distinguishability: raw.distinguishability as string[],
    judge_agreement: [],
    fingerprints: [],
    mde: { statements: [], note: "" },
  };
}

export function loadSimulatedJudgeAgreement(): JudgeAgreementPayload | null {
  const raw = readJson("judge_agreement.json");
  if (raw === null || !Array.isArray(raw.decisions) || !raw.decisions.every(validDecision)) {
    return null;
  }
  return { ...(raw as unknown as JudgeAgreementPayload), placeholder: false };
}
