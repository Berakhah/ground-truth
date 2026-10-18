import type { Metadata } from "next";
import { LeaderboardView } from "@/app/page";
import { PageHeader } from "@/components/PageHeader";
import { SimulatedBanner } from "@/components/SimulatedBanner";
import { requireFixtureRoute } from "@/lib/fixtures";
import { loadSimulatedLeaderboard } from "@/lib/simulated";

// Developer-only view of a simulated run (python -m ground_truth.simulate) through the real
// leaderboard view. Not linked from the UI. Guarded by requireFixtureRoute() (404s unless
// GT_E2E_FIXTURES=1; publish.yml and ci.yml also fail the build if the marker reaches web/out).
export const metadata: Metadata = {
  title: "SIMULATED - Leaderboard",
  robots: { index: false, follow: false },
};

export default function SimulatedLeaderboardExamplePage() {
  requireFixtureRoute();
  const data = loadSimulatedLeaderboard();
  return (
    <>
      <span hidden data-gt-fixture="simulated-example" />
      <SimulatedBanner present={data !== null} />
      {data !== null ? (
        <LeaderboardView data={data} />
      ) : (
        <>
          <PageHeader
            title="Ground Truth"
            subtitle="Simulated run"
            nav={<a href="/methodology">Methodology</a>}
          />
          <main className="report" id="main-content">
            <p>Nothing to show: there is no simulated run on this machine.</p>
          </main>
        </>
      )}
    </>
  );
}
