import type { Metadata } from "next";
import { JudgeAgreementView } from "@/app/judge/page";
import { PageHeader } from "@/components/PageHeader";
import { SimulatedBanner } from "@/components/SimulatedBanner";
import { requireFixtureRoute } from "@/lib/fixtures";
import { loadSimulatedJudgeAgreement } from "@/lib/simulated";

// Developer-only view of a simulated run's judge agreement. See ../../simulated-example.
export const metadata: Metadata = {
  title: "SIMULATED - Judge agreement",
  robots: { index: false, follow: false },
};

export default function SimulatedJudgeExamplePage() {
  requireFixtureRoute();
  const judge = loadSimulatedJudgeAgreement();
  return (
    <>
      <span hidden data-gt-fixture="simulated-judge-example" />
      <SimulatedBanner present={judge !== null} />
      {judge !== null ? (
        <JudgeAgreementView judge={judge} methodologyUrl="/methodology" />
      ) : (
        <>
          <PageHeader
            title="Judge Agreement"
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
