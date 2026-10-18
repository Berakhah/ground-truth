import { Claim } from "@/components/Claim";
import { IntervalBar } from "@/components/IntervalBar";
import { PageHeader } from "@/components/PageHeader";
import { loadLeaderboard, type LeaderboardPayload } from "@/lib/artifacts";

// Extracted from the default page export so /simulated-example can render a simulated run through
// the same view (same pattern as JudgeAgreementView in ./judge/page.tsx).
export function LeaderboardView({ data }: { data: LeaderboardPayload }) {
  return (
    <>
      <PageHeader
        title="Ground Truth"
        subtitle="Pay-application & invoice field-extraction accuracy"
        nav={<a href={data.methodology_url}>Methodology</a>}
      />

      {data.placeholder ? (
        <div className="placeholder-banner" role="status" data-testid="placeholder-banner">
          Placeholder data — no live measurement has run yet. These rows are a
          synthetic demo, not a result.
        </div>
      ) : null}

      <main className="report" id="main-content">
        <p className="distinguishability" data-testid="distinguishability">
          {data.distinguishability.length > 0
            ? data.distinguishability.join(" ")
            : "All models are distinguishable at this sample size."}
        </p>

        {data.held_back_field_types && data.held_back_field_types.length > 0 ? (
          <p className="distinguishability" data-testid="held-back">
            Not in these numbers:{" "}
            {data.held_back_field_types
              .map((held) => `${held.field_type} (${held.reason})`)
              .join("; ")}
            . Where the rubric has a deterministic grader for a type, it is scored by that
            grader instead.
          </p>
        ) : null}

        <div className="table-scroll">
          <table className="leaderboard">
            <caption className="visually-hidden">
              Model leaderboard: accuracy, cost, and latency
            </caption>
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Accuracy</th>
                <th scope="col">
                  Cost
                  {data.rows[0] ? (
                    <span className="th-caveat" data-testid="cost-caveat">
                      {data.rows[0].cost.caveat}
                    </span>
                  ) : null}
                </th>
                <th scope="col" title={data.rows[0]?.latency.caveat ?? "Latency"}>
                  Latency
                  {data.rows[0] ? (
                    // Same caveat as the title tooltip and the print footnote below,
                    // but always in the accessibility tree -- title-only tooltips are
                    // unreachable by keyboard, screen reader, and touch.
                    <span className="visually-hidden" data-testid="latency-caveat">
                      {data.rows[0].latency.caveat}
                    </span>
                  ) : null}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.slot} data-testid="leaderboard-row">
                  <th scope="row">{row.slot}</th>
                  <td>
                    <IntervalBar
                      low={row.accuracy.low}
                      high={row.accuracy.high}
                      point={row.accuracy.point}
                      n={row.accuracy.n}
                    />
                  </td>
                  <td>
                    {/* The list-price caveat is stated once, in the Cost column header
                        above -- CLAUDE.md rule 5 makes it a property of the cost
                        methodology, not a per-row fact, so every row shares it. */}
                    <Claim value={`${row.cost.value} ${row.cost.unit}`} />
                  </td>
                  <td className="latency-cell tabular" title={row.latency.caveat}>
                    p50 {row.latency.p50.toFixed(0)} ms / p95 {row.latency.p95.toFixed(0)} ms
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="print-footnote">
          Latency figures are measured on the free tier ({data.rows[0]?.latency.caveat}); not a
          production SLA.
        </p>
      </main>
    </>
  );
}

export default function Page() {
  return <LeaderboardView data={loadLeaderboard()} />;
}
