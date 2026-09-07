// Static import, not fetch: both the static export and the eventual CSP forbid
// runtime data loading. See ../../artifacts/leaderboard.json (repo root, not under
// web/) -- it is hand-written placeholder data until a real sweep publishes one
// (see that file's own `placeholder: true` field and CLAUDE.md's cost/latency rules).
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
