interface IntervalBarProps {
  low: number;
  high: number;
  point: number;
  n: number;
  /** Domain the track represents. Defaults to the interval itself padded by
   * one interval-width on each side, so a tight CI (the common case for
   * accuracy, e.g. [0.87, 0.96]) still reads as a visible span rather than
   * being swallowed by the point marker at full [0,1] scale. */
  min?: number;
  max?: number;
}

// The signature element: render the interval AS an interval, not a bare number.
// A track spans the measurable domain; a highlighted range spans [low, high];
// a mark sits at `point`. Accent color is used here only -- never on chrome.
export function IntervalBar({ low, high, point, n, min, max }: IntervalBarProps) {
  const pad = Math.max(high - low, 0.01);
  const domainMin = min ?? low - pad;
  const domainMax = max ?? high + pad;
  const toPct = (value: number) => ((value - domainMin) / (domainMax - domainMin)) * 100;
  const left = toPct(low);
  const width = Math.max(toPct(high) - left, 0);

  return (
    <div className="interval-bar">
      <div className="interval-bar__track" aria-hidden="true">
        <div className="interval-bar__range" style={{ left: `${left}%`, width: `${width}%` }} />
        <div className="interval-bar__point" style={{ left: `${toPct(point)}%` }} />
      </div>
      <div className="interval-bar__labels">
        <span className="tabular" data-testid="accuracy-interval">
          {point.toFixed(3)} [{low.toFixed(3)}, {high.toFixed(3)}]
        </span>
        <span className="tabular interval-bar__n" data-testid="accuracy-n">
          n={n}
        </span>
      </div>
    </div>
  );
}
