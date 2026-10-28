import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { loadTriageExample } from "@/lib/artifacts";

function readable(recommendation: string): string {
  return recommendation.replace(/_/g, " ");
}

// A synthetic worked example (docs/triage-example.csv), run through the real triage pipeline
// -- never a real client engagement. Real triage output is CLIENT_CONFIDENTIAL and goes to
// gitignored deliverables/, never to artifacts/ (ground_truth.publish.artifacts.emit_all's
// docstring); this page never reads artifacts/triage.html or anything under deliverables/.
export default function TriagePage() {
  const data = loadTriageExample();

  return (
    <>
      <PageHeader
        title="Triage Report"
        subtitle="Synthetic worked example — never a real engagement"
        nav={<Link href="/">Leaderboard</Link>}
      />

      {data.placeholder ? (
        <div className="placeholder-banner" role="status" data-testid="placeholder-banner">
          {data.note ?? "Synthetic worked example -- not a real client engagement."} Every
          intent, quote, and figure below is fictional.
        </div>
      ) : null}

      <main className="report" data-testid="report" id="main-content">
        <p className="distinguishability">
          Each intent is scored by expected value, not raw accuracy: a wrong extraction&rsquo;s
          cost of error, in the client&rsquo;s own words, decides whether it is worth
          automating.
        </p>

        {data.rows.map((row) => (
          <article key={row.intent} className="triage-row" data-testid="triage-row">
            <h2>{readable(row.intent)}</h2>
            <p className="triage-row__quote">&ldquo;{row.client_quote}&rdquo;</p>

            <dl className="triage-row__calculation" data-testid="calculation">
              <div>
                <dt>Volume / month</dt>
                <dd className="tabular">{row.volume_per_month}</dd>
              </div>
              <div>
                <dt>Current cost / item</dt>
                <dd className="tabular">${row.current_cost_per_item}</dd>
              </div>
              <div>
                <dt>Cost of error</dt>
                <dd className="tabular">
                  {row.cost_of_error === "unbounded" ? "unbounded" : `$${row.cost_of_error}`}
                </dd>
              </div>
              <div>
                <dt>Accuracy</dt>
                <dd className="tabular">
                  {row.accuracy.point.toFixed(3)} [{row.accuracy.low.toFixed(3)},{" "}
                  {row.accuracy.high.toFixed(3)}] n={row.accuracy.n}
                </dd>
              </div>
              <div>
                <dt>Expected value / month</dt>
                <dd className="tabular">
                  ${row.ev.ev_point} [${row.ev.ev_low}, ${row.ev.ev_high}]
                </dd>
              </div>
              <div>
                <dt>Recommendation</dt>
                <dd
                  className={`triage-row__recommendation triage-row__recommendation--${row.ev.recommendation}`}
                >
                  {readable(row.ev.recommendation)}
                </dd>
              </div>
            </dl>

            <p className="triage-row__rationale">{row.ev.rationale}</p>
            <p className="triage-row__flip" data-testid="flip-point">
              {row.flip.sentence}
            </p>
          </article>
        ))}
      </main>
    </>
  );
}
