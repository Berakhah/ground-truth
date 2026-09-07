import type { ReactNode } from "react";

// ponytail: local shim for bok-ui's `Claim` component (not yet published --
// checked `npm view bok-ui`, 404). Design doc (docs/superpowers/specs/
// 2025-09-18-ground-truth-design.md:358,477,495): every derived figure renders
// as a `Claim` carrying `method` and `caveat`, so the honesty requirement is
// discharged by the component, not by remembering a footnote per call site.
// Upgrade path: `import { Claim } from "bok-ui"` once published -- same props.
interface ClaimProps {
  value: ReactNode;
  caveat?: string;
  caveatTestId?: string;
}

export function Claim({ value, caveat, caveatTestId }: ClaimProps) {
  return (
    <span className="claim">
      <span className="claim__value tabular">{value}</span>
      {caveat ? (
        <span className="claim__caveat" data-testid={caveatTestId}>
          {caveat}
        </span>
      ) : null}
    </span>
  );
}
