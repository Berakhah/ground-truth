import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  subtitle: ReactNode;
  nav: ReactNode;
}

// Every report screen (/, /items, /judge, /calibration, /regression, /triage) hand-rolled this
// exact skip-link + masthead + nav shell (review finding: six near-identical copies) --
// extracted once so an accessibility fix (skip-link target, aria-label) lands in one place
// instead of six.
export function PageHeader({ title, subtitle, nav }: PageHeaderProps) {
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="masthead">
        <div className="masthead__heading">
          <h1>{title}</h1>
          <p className="masthead__subtitle">{subtitle}</p>
        </div>
        <nav aria-label="Report">{nav}</nav>
      </header>
    </>
  );
}
