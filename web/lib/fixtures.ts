import { notFound } from "next/navigation";

// Test-only routes render synthetic numbers. They exist for Playwright and must never reach the
// published site: without GT_E2E_FIXTURES=1 the route 404s. publish.yml also greps web/out for
// the data-gt-fixture marker after the build and fails the release if it finds one.
export function requireFixtureRoute(): void {
  if (process.env.GT_E2E_FIXTURES !== "1") {
    notFound();
  }
}
