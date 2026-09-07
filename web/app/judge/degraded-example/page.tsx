import { JudgeAgreementView } from "@/app/judge/page";
import type { JudgeAgreementPayload } from "@/lib/artifacts";

// Test-only fixture route, not linked from anywhere in the real UI. Exists solely so
// web/e2e/judge-degrades.spec.ts can verify JudgeAgreementView degrades gracefully against a
// payload shaped exactly like the REAL ground_truth.publish.artifacts.emit_all() output today
// (flat decisions[], no order_effect/length_effect/confusion_matrix, no per-decision
// statement) -- without mutating the shared artifacts/judge_agreement.json placeholder that
// /judge itself reads and that other E2E tests run concurrently against. A fully static route
// (output: 'export' compatible; no per-request branching, no shared mutable state) rather than
// a file swap, so it carries zero race risk under Playwright's parallel workers.
const REAL_SHAPE_TODAY: JudgeAgreementPayload = {
  decisions: [
    {
      field_type: "money",
      rubric_version: "v1",
      alpha: 0.8,
      alpha_low: 0.7,
      alpha_high: 0.9,
      n_units: 40,
      threshold: 0.667,
      status: "accepted",
      decided_at: "2026-01-01 00:00:00",
    },
    {
      field_type: "free_text_notes",
      rubric_version: "v1",
      alpha: 0.5,
      alpha_low: 0.3,
      alpha_high: 0.6,
      n_units: 20,
      threshold: 0.667,
      status: "rejected",
      decided_at: "2026-01-01 00:00:00",
    },
  ],
};

export default function JudgeDegradedExamplePage() {
  return <JudgeAgreementView judge={REAL_SHAPE_TODAY} methodologyUrl="/methodology" />;
}
