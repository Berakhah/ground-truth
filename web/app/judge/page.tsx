import { ConfusionMatrix } from "@/components/ConfusionMatrix";
import { IntervalBar } from "@/components/IntervalBar";
import { PageHeader } from "@/components/PageHeader";
import { loadJudgeAgreement, loadLeaderboard, type JudgeAgreementPayload } from "@/lib/artifacts";

// Mirrors ground_truth.graders.judge.agreement.REJECTION_THRESHOLD (0.667, pinned to
// docs/analysis-plan.md's plan_version). Each decision already carries its own `threshold`
// (emit_all dumps it per-row from judge_decisions), so this is only the last-resort display
// value for the rare case no decisions exist at all -- not a second source of truth.
const FALLBACK_THRESHOLD = 0.667;

interface JudgeAgreementViewProps {
  judge: JudgeAgreementPayload;
  methodologyUrl: string;
}

// Extracted from the default page export so /judge/degraded-example (a second, static-only
// route, see that folder) can render the exact same view against a hardcoded payload shaped
// like the real, narrower emit_all() output -- proving this degrades instead of crashing
// without mutating the shared artifacts/judge_agreement.json placeholder (which /judge itself
// reads, and which other E2E tests run concurrently against).
export function JudgeAgreementView({ judge, methodologyUrl }: JudgeAgreementViewProps) {
  const threshold = judge.decisions[0]?.threshold ?? FALLBACK_THRESHOLD;

  return (
    <>
      <PageHeader
        title="Judge Agreement"
        subtitle="Judge-versus-human agreement, by field type"
        nav={<a href={methodologyUrl}>Methodology</a>}
      />

      {judge.placeholder ? (
        <div className="placeholder-banner" role="status" data-testid="placeholder-banner">
          Placeholder data — no live measurement has run yet. These rows are a synthetic demo,
          not a result.
        </div>
      ) : null}

      <main className="report" id="main-content">
        <p className="threshold-notice" data-testid="threshold-notice">
          A field type is accepted for headline scoring only when judge-human agreement
          (Krippendorff&rsquo;s alpha) meets or exceeds the pre-registered threshold of{" "}
          <span className="tabular">{threshold}</span>. Field types below threshold are
          reported as rejected and not used for headline scoring, never silently dropped.
        </p>

        <div className="table-scroll">
          <table className="report-table agreement-table" data-testid="agreement-table">
            <caption className="visually-hidden">
              Judge-versus-human agreement by field type
            </caption>
            <thead>
              <tr>
                <th scope="col">Field type</th>
                <th scope="col">Alpha</th>
                <th scope="col">Status</th>
                <th scope="col">Statement</th>
              </tr>
            </thead>
            <tbody>
              {judge.decisions.map((decision) => (
                <tr key={decision.field_type} data-testid="agreement-row">
                  <th scope="row">{decision.field_type}</th>
                  <td data-testid="alpha-value">
                    <IntervalBar
                      low={decision.alpha_low}
                      high={decision.alpha_high}
                      point={decision.alpha}
                      n={decision.n_units}
                    />
                  </td>
                  <td className={`agreement-status agreement-status--${decision.status}`}>
                    {decision.status === "accepted" ? "Accepted" : "Rejected"}
                  </td>
                  {/* emit_all's real output carries no per-decision statement (see
                      AgreementDecision's own comment in lib/artifacts.ts) -- fall back to an
                      em dash rather than rendering "undefined" or leaving the cell blank
                      without explanation. */}
                  <td>{decision.statement ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <section className="effects" aria-label="Judge bias controls">
          <div className="effects__item" data-testid="order-effect">
            <h2>Order effect</h2>
            {judge.order_effect ? (
              <>
                <p>{judge.order_effect.statement}</p>
                <p className="tabular effects__figure">
                  First-shown {(judge.order_effect.order_0_rate * 100).toFixed(0)}% /
                  second-shown {(judge.order_effect.order_1_rate * 100).toFixed(0)}% (n=
                  {judge.order_effect.n})
                </p>
              </>
            ) : (
              <p className="effects__figure">
                Not yet measured — no order-effect data has been published.
              </p>
            )}
          </div>
          <div className="effects__item" data-testid="length-effect">
            <h2>Length effect</h2>
            {judge.length_effect ? (
              <>
                <p>{judge.length_effect.statement}</p>
                <p className="tabular effects__figure">
                  By response-length quintile:{" "}
                  {judge.length_effect.quintile_rates.map((rate) => rate.toFixed(2)).join(", ")}
                  {" "}(n={judge.length_effect.n})
                </p>
              </>
            ) : (
              <p className="effects__figure">
                Not yet measured — no length-effect data has been published.
              </p>
            )}
          </div>
        </section>

        {judge.confusion_matrix ? (
          <ConfusionMatrix
            labels={judge.confusion_matrix.labels}
            counts={judge.confusion_matrix.counts}
          />
        ) : (
          <p className="confusion-matrix-empty" data-testid="confusion-matrix">
            Not yet measured — no confusion matrix has been published.
          </p>
        )}

        {judge.note ? <p className="print-footnote">{judge.note}</p> : null}
      </main>
    </>
  );
}

export default function JudgePage() {
  const judge = loadJudgeAgreement();
  const { methodology_url } = loadLeaderboard();
  return <JudgeAgreementView judge={judge} methodologyUrl={methodology_url} />;
}
