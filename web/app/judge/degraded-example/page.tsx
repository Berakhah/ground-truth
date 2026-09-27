import type { Metadata } from "next";
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
//
// It still ships in the static export (Next has no "test-only, exclude from output: export"
// primitive), so it needs the same disclosure every other page gives its synthetic data --
// otherwise a stray visitor or crawler sees plausible alpha/accepted/rejected numbers with no
// indication they're a fixture. noindex here, and JudgeAgreementView's own `placeholder`
// banner below, cover that (review finding, post task-46).
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

const REAL_SHAPE_TODAY: JudgeAgreementPayload = {
  // Reuses JudgeAgreementView's existing placeholder-banner branch (the same one /, /items,
  // and /judge all use) rather than inventing separate fixture-only chrome.
  placeholder: true,
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
    {
      // emit_all's shape for a 0/0 alpha: nulls plus the reason it writes beside them.
      field_type: "currency_code",
      rubric_version: "v1",
      alpha: null,
      alpha_low: null,
      alpha_high: null,
      n_units: 60,
      threshold: 0.667,
      status: "rejected",
      decided_at: "2026-01-01 00:00:00",
      statement:
        "Krippendorff's alpha is undefined, n=60 -- judge and human gave every unit the same " +
        "verdict, so this sample cannot distinguish the judge from one that always gives that " +
        "verdict. Treated as below the threshold of 0.667; this field type is not used for " +
        "headline scoring and is reported as not measured.",
    },
    {
      // A defined alpha whose every bootstrap resample was 0/0: no interval, so rejected.
      field_type: "invoice_number",
      rubric_version: "v1",
      alpha: 0,
      alpha_low: null,
      alpha_high: null,
      n_units: 10,
      threshold: 0.667,
      status: "rejected",
      decided_at: "2026-01-01 00:00:00",
      statement:
        "Judge-human agreement on invoice_number: Krippendorff's alpha = 0.000 (interval could " +
        "not be estimated: unit-bootstrap-percentile, 2 of 2 undefined resamples excluded), " +
        "n=10. Below the pre-registered threshold of 0.667; this field type is not used for " +
        "headline scoring and is reported as not measured.",
      alpha_method: "unit-bootstrap-percentile, 2 of 2 undefined resamples excluded",
    },
  ],
};

export default function JudgeDegradedExamplePage() {
  return <JudgeAgreementView judge={REAL_SHAPE_TODAY} methodologyUrl="/methodology" />;
}
