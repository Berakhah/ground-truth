import { ReliabilityDiagram } from "@/components/ReliabilityDiagram";
import { loadCalibration, loadLeaderboard, type CalibrationCurve } from "@/lib/artifacts";

// docs/rubric.md's eight FieldType values, in the order they're defined there -- the full
// universe a calibration curve could exist for. Money is listed first on purpose: it is the
// one field type the placeholder data actually calibrates, so the page's first
// confidence-meter is a real CALIBRATED example rather than an uncalibrated placeholder.
const FIELD_TYPES = [
  "money",
  "percent",
  "date",
  "identifier",
  "party_name",
  "enum_category",
  "count",
  "line_item_description",
];

interface ConfidenceMeterProps {
  fieldType: string;
  curve?: CalibrationCurve;
}

// Inline element, not a separate component file (task-47 brief): a ConfidenceMeter always
// receives the whole Calibration object for its field type (state/basis/n), never a bare
// float -- a float has no way to carry "uncalibrated".
function ConfidenceMeter({ fieldType, curve }: ConfidenceMeterProps) {
  const state = curve ? "CALIBRATED" : "UNCALIBRATED";
  return (
    <div
      className={`confidence-meter confidence-meter--${state.toLowerCase()}`}
      data-testid="confidence-meter"
      data-calibration-state={state}
    >
      <span className="confidence-meter__field">{fieldType}</span>
      {curve ? (
        <span className="tabular confidence-meter__n">n={curve.n}</span>
      ) : (
        <span className="confidence-meter__label">
          Uncalibrated &mdash; no replicate-agreement curve fitted yet
        </span>
      )}
    </div>
  );
}

export default function CalibrationPage() {
  const data = loadCalibration();
  const { methodology_url } = loadLeaderboard();
  const curveByFieldType = new Map(data.curves.map((curve) => [curve.field_type, curve]));

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="masthead">
        <div className="masthead__heading">
          <h1>Calibration</h1>
          <p className="masthead__subtitle">Reliability curves, by field type</p>
        </div>
        <nav aria-label="Report">
          <a href={methodology_url}>Methodology</a>
        </nav>
      </header>

      {data.placeholder ? (
        <div className="placeholder-banner" role="status" data-testid="placeholder-banner">
          Placeholder data — no live measurement has run yet. These curves are a synthetic
          demo, not a result.
        </div>
      ) : null}

      <main className="report" id="main-content">
        <p className="signal-notice" data-testid="signal-notice">
          The confidence signal calibrated here is <strong>replicate agreement</strong> — the
          fraction of n&ge;5 repeated runs per item that agree with each other, not a model&rsquo;s
          own stated confidence, which many providers do not expose at all. Each curve maps that
          agreement rate to the empirical probability of being correct.
        </p>

        <p className="source-split-notice" data-testid="source-split">
          Curves are fit on the public split and validated against the private, held-out split
          (public-fit/private-validate); the published sample size is always the validation
          sample the curve was checked against, never the sample it was fit to.
        </p>

        {data.curves.length === 0 ? (
          <p className="empty-state" data-testid="curves-empty">
            No calibration curves fitted yet.
          </p>
        ) : (
          <div className="reliability-diagrams">
            {data.curves.map((curve) => (
              <ReliabilityDiagram key={curve.field_type} curve={curve} />
            ))}
          </div>
        )}

        <table className="report-table threshold-table" data-testid="threshold-table">
          <caption className="visually-hidden">
            Threshold recommendations by field type and target precision
          </caption>
          <thead>
            <tr>
              <th scope="col">Field type</th>
              <th scope="col">Target precision</th>
              <th scope="col">Threshold</th>
            </tr>
          </thead>
          <tbody>
            {data.curves.flatMap((curve) =>
              curve.threshold_recommendations.map((rec) => (
                <tr key={`${curve.field_type}-${rec.target_precision}`}>
                  <th scope="row">{curve.field_type}</th>
                  <td className="tabular">{rec.target_precision.toFixed(2)}</td>
                  <td className="tabular">{rec.threshold.toFixed(3)}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>

        <section aria-label="Confidence signal by field type" className="confidence-meters">
          <h2>Confidence signal by field type</h2>
          {FIELD_TYPES.map((fieldType) => (
            <ConfidenceMeter
              key={fieldType}
              fieldType={fieldType}
              curve={curveByFieldType.get(fieldType)}
            />
          ))}
        </section>
      </main>
    </>
  );
}
