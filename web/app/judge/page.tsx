import { ConfusionMatrix } from "@/components/ConfusionMatrix";
import { IntervalBar } from "@/components/IntervalBar";
import { loadJudgeAgreement, loadLeaderboard } from "@/lib/artifacts";

export default function JudgePage() {
  const judge = loadJudgeAgreement();
  const { methodology_url } = loadLeaderboard();

  return (
    <>
      <header className="masthead">
        <div className="masthead__heading">
          <h1>Judge Agreement</h1>
          <p className="masthead__subtitle">Judge-versus-human agreement, by field type</p>
        </div>
        <nav aria-label="Report">
          <a href={methodology_url}>Methodology</a>
        </nav>
      </header>

      {judge.placeholder ? (
        <div className="placeholder-banner" role="status" data-testid="placeholder-banner">
          Placeholder data — no live measurement has run yet. These rows are a synthetic demo,
          not a result.
        </div>
      ) : null}

      <main className="report">
        <p className="threshold-notice" data-testid="threshold-notice">
          A field type is accepted for headline scoring only when judge-human agreement
          (Krippendorff&rsquo;s alpha) meets or exceeds the pre-registered threshold of{" "}
          <span className="tabular">{judge.threshold}</span>. Field types below threshold are
          reported as rejected and not used for headline scoring, never silently dropped.
        </p>

        <table className="report-table agreement-table" data-testid="agreement-table">
          <caption className="visually-hidden">Judge-versus-human agreement by field type</caption>
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
                    low={decision.alpha_ci.low}
                    high={decision.alpha_ci.high}
                    point={decision.alpha}
                    n={decision.n_units}
                  />
                </td>
                <td className={`agreement-status agreement-status--${decision.status.toLowerCase()}`}>
                  {decision.status === "ACCEPTED" ? "Accepted" : "Rejected"}
                </td>
                <td>{decision.statement}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <section className="effects" aria-label="Judge bias controls">
          <div className="effects__item" data-testid="order-effect">
            <h2>Order effect</h2>
            <p>{judge.order_effect.statement}</p>
            <p className="tabular effects__figure">
              First-shown {(judge.order_effect.order_0_rate * 100).toFixed(0)}% / second-shown{" "}
              {(judge.order_effect.order_1_rate * 100).toFixed(0)}% (n={judge.order_effect.n})
            </p>
          </div>
          <div className="effects__item" data-testid="length-effect">
            <h2>Length effect</h2>
            <p>{judge.length_effect.statement}</p>
            <p className="tabular effects__figure">
              By response-length quintile:{" "}
              {judge.length_effect.quintile_rates.map((rate) => rate.toFixed(2)).join(", ")} (n=
              {judge.length_effect.n})
            </p>
          </div>
        </section>

        <ConfusionMatrix
          labels={judge.confusion_matrix.labels}
          counts={judge.confusion_matrix.counts}
        />

        {judge.note ? <p className="print-footnote">{judge.note}</p> : null}
      </main>
    </>
  );
}
