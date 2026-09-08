import { loadLeaderboard, loadRegression } from "@/lib/artifacts";

export default function RegressionPage() {
  const data = loadRegression();
  const { methodology_url } = loadLeaderboard();
  const nullAlerts = data.alerts.filter((alert) => !alert.detected);

  return (
    <>
      <header className="masthead">
        <div className="masthead__heading">
          <h1>Regression Watch</h1>
          <p className="masthead__subtitle">
            Scheduled drift detection
            {data.look !== undefined && data.total_looks !== undefined
              ? ` — look ${data.look} of ${data.total_looks}`
              : null}
          </p>
        </div>
        <nav aria-label="Report">
          <a href={methodology_url}>Methodology</a>
        </nav>
      </header>

      {data.placeholder ? (
        <div className="placeholder-banner" role="status" data-testid="placeholder-banner">
          Placeholder data — no live regression watch has run yet. These alerts are a
          synthetic demo, not a result.
        </div>
      ) : null}

      <main className="report">
        {/* Every alert renders as its full statement -- the sentence Alert.statement already
            is, never a bare arrow or delta. See ground_truth.regression.detect: `detected`
            requires BOTH the O'Brien-Fleming sequential boundary and the Benjamini-Hochberg
            corrected p-value, and the statement names both tests regardless of the result. */}
        {data.alerts.length === 0 ? (
          <p className="empty-state" data-testid="alerts-empty">
            No comparisons recorded for this look.
          </p>
        ) : (
          <ul className="alert-list">
            {data.alerts.map((alert) => (
              <li
                key={`${alert.slot}-${alert.field_type}`}
                className={`alert alert--${alert.detected ? "detected" : "null"}`}
                data-testid="alert"
              >
                <h2>
                  {alert.slot} / {alert.field_type}
                </h2>
                <p>{alert.statement}</p>
              </li>
            ))}
          </ul>
        )}

        <section aria-label="What a null result means" data-testid="mde-notice">
          <h2>What a null result means</h2>
          <p>
            A &ldquo;no change detected&rdquo; alert states the minimum effect size this look
            could have detected, not that no drift exists.
          </p>
          {nullAlerts.length === 0 ? (
            <p className="effects__figure">No null-result alerts at this look.</p>
          ) : (
            <ul>
              {nullAlerts.map((alert) => (
                <li key={`${alert.slot}-${alert.field_type}-mde`}>{alert.statement}</li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="Version fingerprints" data-testid="fingerprints">
          <h2>Version fingerprints</h2>
          {data.fingerprints.length === 0 ? (
            <p className="effects__figure">No fingerprint data published for this look.</p>
          ) : (
            <ul className="fingerprint-list">
              {data.fingerprints.map((fingerprint) => (
                <li
                  key={fingerprint.slot}
                  className={`fingerprint fingerprint--${fingerprint.status.toLowerCase()}`}
                >
                  <span className="fingerprint__slot tabular">{fingerprint.slot}</span>{" "}
                  <span className="fingerprint__status">{fingerprint.status}</span>
                  <p>{fingerprint.statement}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </>
  );
}
