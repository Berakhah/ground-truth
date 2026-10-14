// Static import, not fetch: both the static export and the eventual CSP forbid
// runtime data loading. See ../../artifacts/leaderboard.json (repo root, not under
// web/) -- it is hand-written placeholder data until a real sweep publishes one
// (see that file's own `placeholder: true` field and CLAUDE.md's cost/latency rules).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import calibration from "../../artifacts/calibration.json";
import judgeAgreement from "../../artifacts/judge_agreement.json";
import leaderboard from "../../artifacts/leaderboard.json";
import regression from "../../artifacts/regression.json";
import triageExample from "../../artifacts/triage_example.json";

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
  // Whether this verdict counts toward the headline number (a judge verdict counts only when
  // the slot's current judge has an accepted agreement decision). Optional: the committed
  // placeholder verdicts predate it.
  counts_toward_headline?: boolean;
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
// (one `_judge_decision` dict per `judge_decisions` row, flat alpha/alpha_low/alpha_high with
// non-finite values mapped to null) -- not
// ground_truth.publish.leaderboard._agreement_to_dict, which has a similar-looking but
// different shape (nested alpha_ci, uppercase status) and is only ever embedded inside
// leaderboard.json's `judge_agreement` array, never written to this standalone file. Corrected
// post-review (task-46-report.md): the first draft was modeled on the wrong emitter.
export interface AgreementDecision {
  field_type: string;
  // One decision per (field type, judge). Optional: the placeholder-era shape had no judge.
  judge_slot?: string;
  rubric_version: string;
  // null when alpha is 0/0 (judge and human gave every unit one verdict): emit_all maps the
  // stored NaN to null. alpha_low/alpha_high are also null, with a defined alpha, when every
  // bootstrap resample was 0/0 and the interval could not be estimated.
  alpha: number | null;
  alpha_low: number | null;
  alpha_high: number | null;
  n_units: number;
  threshold: number;
  status: "accepted" | "rejected";
  decided_at: string;
  // The statement assess() wrote and the interval's method (which records how many 0/0
  // resamples were excluded), both stored with the decision. null on decisions recorded before
  // they were stored; optional because the placeholder artifact predates them.
  statement?: string | null;
  alpha_method?: string | null;
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

// Judge verdicts scored inconclusive (no majority, counted as incorrect): `count` of `n`
// judge verdicts for this model slot and judge. Sorted by (slot, judge_slot) by the emitter.
export interface InconclusiveCount {
  slot: string;
  judge_slot: string;
  count: number;
  n: number;
}

export interface JudgeAgreementPayload {
  placeholder?: boolean;
  decisions: AgreementDecision[];
  inconclusive?: InconclusiveCount[];
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

// Shape matches the REAL producer of this exact file -- ground_truth.calibrate.export's
// export_curves -- not artifacts.py's emit_all, whose own calibration.json write today is a
// bare `{"curves": [], "note": ...}` placeholder (task-47 brief: two separate, standalone
// publish paths with no runtime coupling, same as the regression watch below). Typed against
// the richer shape so a real export_curves run degrades nothing; schema_version/note are
// optional extras neither producer's shape depends on.
export interface ThresholdRecommendation {
  target_precision: number;
  threshold: number;
}

export interface CalibrationCurve {
  field_type: string;
  method: string;
  curve_points: [number, number][];
  n: number;
  fitted_at: string;
  rubric_version: string;
  source_split: string;
  threshold_recommendations: ThresholdRecommendation[];
}

export interface CalibrationPayload {
  schema_version?: string;
  placeholder?: boolean;
  note?: string;
  curves: CalibrationCurve[];
}

export function loadCalibration(): CalibrationPayload {
  return calibration as CalibrationPayload;
}

// Shape matches ground_truth.regression.detect.Alert and
// ground_truth.regression.fingerprint.SlotFingerprint exactly (task-47 brief: no
// reconciliation needed here, unlike calibration.json above).
export interface RegressionInterval {
  point: number;
  low: number;
  high: number;
  n: number;
  method: string;
}

export interface RegressionAlert {
  slot: string;
  field_type: string;
  baseline: RegressionInterval;
  current: RegressionInterval;
  z: number;
  adjusted_p: number;
  look: number;
  total_looks: number;
  detected: boolean;
  statement: string;
}

export interface RegressionFingerprint {
  slot: string;
  status: "STABLE" | "CHANGED" | "NOT_EXPOSED";
  values: string[];
  first_seen: string;
  last_seen: string;
  statement: string;
}

export interface RegressionPayload {
  look?: number;
  total_looks?: number;
  generated_at?: string;
  placeholder?: boolean;
  note?: string;
  alerts: RegressionAlert[];
  fingerprints: RegressionFingerprint[];
}

export function loadRegression(): RegressionPayload {
  return regression as RegressionPayload;
}

// Shape matches ground_truth.triage.export_example's output -- a synthetic worked example
// (docs/triage-example.csv) run through the real, already-tested triage.report pipeline
// (load_intents -> expected_value.evaluate -> sensitivity.find_flip_point). Never a real
// client engagement: real triage output is CLIENT_CONFIDENTIAL and goes to gitignored
// deliverables/, never to artifacts/ (ground_truth.publish.artifacts.emit_all's docstring).
export interface TriageAccuracy {
  point: number;
  low: number;
  high: number;
  n: number;
  method: string;
}

export interface TriageEV {
  recommendation: string;
  ev_low: string;
  ev_point: string;
  ev_high: string;
  n: number;
  rationale: string;
}

export interface TriageFlip {
  sentence: string;
  flips_at: string | null;
}

export interface TriageRow {
  intent: string;
  volume_per_month: number;
  current_cost_per_item: string;
  cost_of_error: string;
  client_quote: string;
  accuracy: TriageAccuracy;
  ev: TriageEV;
  flip: TriageFlip;
}

export interface TriageExamplePayload {
  placeholder?: boolean;
  note?: string;
  rows: TriageRow[];
}

export function loadTriageExample(): TriageExamplePayload {
  return triageExample as TriageExamplePayload;
}
