// Shown above every route that renders a simulated run. Loud on purpose: nothing on these pages
// is a measurement of any model, and a screenshot of one must not be mistakable for a result.
export function SimulatedBanner({ present }: { present: boolean }) {
  return (
    <div className="placeholder-banner" role="status" data-testid="simulated-banner">
      <strong>SIMULATED.</strong>{" "}
      {present
        ? "Every number on this page comes from a simulated provider (python -m ground_truth.simulate), not from any model. Slot names start sim-; the prices are invented. Never quote it."
        : "No usable simulated run was found in data/simulated/. Run python -m ground_truth.simulate, then reload."}
    </div>
  );
}
