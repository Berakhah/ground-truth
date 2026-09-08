import type { CalibrationCurve } from "@/lib/artifacts";

interface ReliabilityDiagramProps {
  curve: CalibrationCurve;
}

const SIZE = 200;
const PAD = 24;

function toSvgX(x: number): number {
  return PAD + x * (SIZE - 2 * PAD);
}

function toSvgY(y: number): number {
  return SIZE - PAD - y * (SIZE - 2 * PAD);
}

// One reliability diagram per calibrated field type: the fitted curve (accent) against the
// diagonal of perfect calibration (hairline) -- plain inline SVG, not a charting library, the
// same non-goal this project already applied to IntervalBar and ConfusionMatrix.
export function ReliabilityDiagram({ curve }: ReliabilityDiagramProps) {
  const points = curve.curve_points
    .map(([x, y]) => `${toSvgX(x).toFixed(1)},${toSvgY(y).toFixed(1)}`)
    .join(" ");

  // Mean absolute distance of each fitted point from the diagonal it is plotted against --
  // derived entirely from curve_points already published, never a second, invented statistic.
  const divergence =
    curve.curve_points.reduce((sum, [x, y]) => sum + Math.abs(y - x), 0) /
    curve.curve_points.length;

  return (
    <figure className="reliability-diagram">
      <svg
        className="reliability-diagram__svg"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={`Reliability diagram for ${curve.field_type}, fitted by ${curve.method}`}
      >
        <line
          className="reliability-diagram__diagonal"
          x1={toSvgX(0)}
          y1={toSvgY(0)}
          x2={toSvgX(1)}
          y2={toSvgY(1)}
        />
        <polyline className="reliability-diagram__curve" points={points} />
        {curve.curve_points.map(([x, y]) => (
          <circle
            key={`${x}-${y}`}
            className="reliability-diagram__point"
            cx={toSvgX(x)}
            cy={toSvgY(y)}
          />
        ))}
      </svg>
      <figcaption>
        <span className="tabular" data-testid="curve-n">
          {curve.field_type} ({curve.method}) &mdash; n={curve.n}
        </span>
        <p className="reliability-diagram__divergence">
          Mean divergence from the diagonal:{" "}
          <span className="tabular">{divergence.toFixed(3)}</span>. A growing value here means
          replicate agreement is diverging further from stated confidence &mdash; the curve is
          compensating for a less trustworthy raw signal.
        </p>
      </figcaption>
    </figure>
  );
}
