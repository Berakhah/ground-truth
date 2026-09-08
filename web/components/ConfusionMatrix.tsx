interface ConfusionMatrixProps {
  labels: string[];
  counts: number[][];
}

// A confusion matrix is a small grid of counts -- a plain table, not a charting library (the
// project's non-goal against building generic viz tooling for a handful of cells applies here
// same as everywhere else). Judge verdict on the rows, human verdict on the columns.
export function ConfusionMatrix({ labels, counts }: ConfusionMatrixProps) {
  return (
    <div className="table-scroll">
      <table className="confusion-matrix" data-testid="confusion-matrix">
        <caption>Judge vs. human verdict (rows: judge, columns: human)</caption>
        <thead>
          <tr>
            <th scope="col" />
            {labels.map((label) => (
              <th scope="col" key={label}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {counts.map((row, i) => (
            <tr key={labels[i] ?? i}>
              <th scope="row">{labels[i] ?? i}</th>
              {row.map((count, j) => (
                <td className="tabular" key={labels[j] ?? j}>
                  {count}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
