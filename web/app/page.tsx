import { Claim } from "@/components/Claim";
import { IntervalBar } from "@/components/IntervalBar";
import { loadLeaderboard } from "@/lib/artifacts";

export default function Page() {
  const data = loadLeaderboard();

  return (
    <>
      <header className="masthead">
        <div className="masthead__heading">
          <h1>Ground Truth</h1>
          <p className="masthead__subtitle">
            Pay-application &amp; invoice field-extraction accuracy
          </p>
        </div>
        <nav aria-label="Report">
          <a href={data.methodology_url}>Methodology</a>
        </nav>
      </header>

      {data.placeholder ? (
        <div className="placeholder-banner" role="status" data-testid="placeholder-banner">
          Placeholder data — no live measurement has run yet. These rows are a
          synthetic demo, not a result.
        </div>
      ) : null}

      <main className="report">
        <p className="distinguishability" data-testid="distinguishability">
          {data.distinguishability.length > 0
            ? data.distinguishability.join(" ")
            : "All models are distinguishable at this sample size."}
        </p>

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

        <p className="print-footnote">
          Latency figures are measured on the free tier ({data.rows[0]?.latency.caveat}); not a
          production SLA.
        </p>
      </main>
    </>
  );
}
