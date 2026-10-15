import type { Metadata } from "next";
import { JudgeAgreementView } from "@/app/judge/page";
import type { JudgeAgreementPayload } from "@/lib/artifacts";
import { requireFixtureRoute } from "@/lib/fixtures";

// Test-only fixture route, not linked from the real UI (same pattern as ../degraded-example).
// Exists so web/e2e/judge.spec.ts can check that two judges on one field type both render and
// that the inconclusive table appears, without putting fake numbers in the committed
// artifacts/judge_agreement.json placeholder. Guarded by requireFixtureRoute() (404s unless
// GT_E2E_FIXTURES=1; publish.yml also fails the release if it reaches web/out). As defence in
// depth it is bannered as placeholder data and noindex.
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

const MULTI_JUDGE: JudgeAgreementPayload = {
  placeholder: true,
  decisions: [
    {
      field_type: "money",
      judge_slot: "judge_a",
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
      field_type: "money",
      judge_slot: "judge_b",
      rubric_version: "v1",
      alpha: 0.5,
      alpha_low: 0.3,
      alpha_high: 0.6,
      n_units: 40,
      threshold: 0.667,
      status: "rejected",
      decided_at: "2026-01-01 00:00:00",
    },
  ],
  inconclusive: [
    { slot: "slot_one", judge_slot: "judge_a", count: 3, n: 12 },
    { slot: "slot_one", judge_slot: "judge_b", count: 0, n: 12 },
  ],
};

export default function JudgeMultiJudgeExamplePage() {
  requireFixtureRoute();
  return (
    <>
      <span hidden data-gt-fixture="multi-judge-example" />
      <JudgeAgreementView judge={MULTI_JUDGE} methodologyUrl="/methodology" />
    </>
  );
}
