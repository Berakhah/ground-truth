// Static import, not fetch: both the static export and the eventual CSP forbid
// runtime data loading. See ../../artifacts/leaderboard.json (repo root, not under
// web/) -- it is hand-written placeholder data until a real sweep publishes one
// (see that file's own `placeholder: true` field and CLAUDE.md's cost/latency rules).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import judgeAgreement from "../../artifacts/judge_agreement.json";
import leaderboard from "../../artifacts/leaderboard.json";

export interface AccuracyEstimate {
  point: number;
  low: number;
  high: number;
  n: number;
  method: string;
}

export interface CostClaim {
  value: string;
  unit: string;
  method: string;
  source_url: string;
  retrieved_at: string;
  caveat: string;
}

export interface LatencyDistribution {
  p50: number;
  p95: number;
  n: number;
  ecdf_x: number[];
  ecdf_y: number[];
  caveat: string;
}

export interface LeaderboardRow {
  slot: string;
  accuracy: AccuracyEstimate;
  cost: CostClaim;
  latency: LatencyDistribution;
  per_field: Record<string, AccuracyEstimate>;
}

export interface LeaderboardPayload {
  version: string;
  as_of: string;
  methodology_url: string;
  placeholder?: boolean;
  rows: LeaderboardRow[];
  distinguishability: string[];
  judge_agreement: unknown[];
  fingerprints: unknown[];
  mde: { statements: string[]; note: string };
}

export function loadLeaderboard(): LeaderboardPayload {
  return leaderboard as LeaderboardPayload;
}

// verdicts_public.jsonl (repo root artifacts/, hand-written placeholder data -- see
// task-46-report.md) is line-delimited, one PublicVerdict per line, matching
// ground_truth/publish/artifacts.py's PublicVerdict dataclass exactly (`reason` included --
// see that module for the additive extension that put it there). resolveJsonModule only
// covers `.json`, so this is read with `fs` at render time (server component only, never
// imported from a "use client" module) rather than statically imported like leaderboard.json.
export interface PublicVerdict {
  item_id: string;
  slot: string;
  field_name: string;
  correct: boolean;
  grader_id: string;
  grader_version: string;
  rubric_version: string;
  reason: string;
}

export function loadPublicVerdicts(): PublicVerdict[] {
  const path = join(process.cwd(), "..", "artifacts", "verdicts_public.jsonl");
  const text = readFileSync(path, "utf-8");
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as PublicVerdict);
}

// Shape matches the REAL writer of this exact file -- ground_truth.publish.artifacts.emit_all
// (its `decisions` list comprehension, verbatim dump of the `judge_decisions` table) -- not
// ground_truth.publish.leaderboard._agreement_to_dict, which has a similar-looking but
// different shape (nested alpha_ci, a `statement` field) and is only ever embedded inside
// leaderboard.json's `judge_agreement` array, never written to this standalone file. Corrected
// post-review (task-46-report.md): the first draft was modeled on the wrong emitter.
export interface AgreementDecision {
  field_type: string;
  rubric_version: string;
  alpha: number;
  alpha_low: number;
  alpha_high: number;
  n_units: number;
  threshold: number;
  status: "accepted" | "rejected";
  decided_at: string;
  // emit_all's DB-backed dump carries none of AgreementReport's prose -- optional so a real
  // publish (which will never set this) still renders instead of showing `undefined`.
  statement?: string;
}

export interface OrderEffectSummary {
  statement: string;
  order_0_rate: number;
  order_1_rate: number;
  difference: number;
  n: number;
}

export interface LengthEffectSummary {
  statement: string;
  quintile_rates: number[];
  n: number;
}

export interface ConfusionMatrixData {
  labels: string[];
  counts: number[][];
}

export interface JudgeAgreementPayload {
  placeholder?: boolean;
  decisions: AgreementDecision[];
  // None of these three are emitted by ground_truth.publish.artifacts.emit_all today -- it
  // scopes this file to a verbatim dump of the judge_decisions table (Task 40's deliberate
  // ruling), and order/length effects and confusion matrices aren't stored anywhere queryable
  // yet. Optional here so the day a real (narrower) publish overwrites this placeholder, the
  // page degrades to an honest "not yet measured" state instead of crashing on `undefined`.
  order_effect?: OrderEffectSummary;
  length_effect?: LengthEffectSummary;
  confusion_matrix?: ConfusionMatrixData;
  note?: string;
}

export function loadJudgeAgreement(): JudgeAgreementPayload {
  return judgeAgreement as JudgeAgreementPayload;
}
