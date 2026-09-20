import { ItemsTable } from "@/components/ItemsTable";
import { PageHeader } from "@/components/PageHeader";
import { loadLeaderboard, loadPublicVerdicts } from "@/lib/artifacts";

export default function ItemsPage() {
  const verdicts = loadPublicVerdicts();
  const { methodology_url } = loadLeaderboard();

  return (
    <>
      <PageHeader
        title="Item Explorer"
        subtitle="Public-split verdicts, by field and failure mode"
        nav={<a href={methodology_url}>Methodology</a>}
      />

      {/* verdicts_public.jsonl is a line-delimited list of PublicVerdict records -- it has no
          top-level slot for a `placeholder` flag the way leaderboard.json and
          judge_agreement.json do, so this banner is unconditional: the file is entirely
          hand-written placeholder data (no live sweep has published one yet). */}
      <div className="placeholder-banner" role="status" data-testid="placeholder-banner">
        Placeholder data — no live measurement has run yet. These rows are a synthetic demo,
        not a result.
      </div>

      <main className="report" id="main-content">
        <p className="split-notice" data-testid="split-notice">
          This explorer shows the 120-item public split. The 180-item private split is
          withheld; its hashes are published and headline numbers are computed against it.
        </p>

        <ItemsTable verdicts={verdicts} />
      </main>
    </>
  );
}
