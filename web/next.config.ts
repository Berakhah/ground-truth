import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  // lib/artifacts.ts imports ../../artifacts/leaderboard.json, which lives at the
  // repo root outside web/ on purpose (never published under web/public/). Both
  // bundlers refuse to resolve modules outside the project root unless told to:
  // `externalDir` for webpack, `turbopack.root` for Turbopack (the dev default).
  experimental: {
    externalDir: true,
  },
  turbopack: {
    root: path.join(__dirname, ".."),
  },
  // Task 46: Playwright's baseURL (playwright.config.ts) is http://127.0.0.1:3000, which
  // Next's dev-origin check (introduced ahead of `allowedDevOrigins` going stable) treats as
  // cross-origin from "localhost" and silently drops dev-asset requests for -- Task 45's
  // leaderboard page never exercised this because it has no client interactivity to break,
  // but Task 46's filter/search controls are client components, and a dropped hydration
  // bundle means onChange never fires even though the raw DOM element still visibly updates
  // (Playwright's driver sets it directly). Without this, every interactive E2E test here
  // fails while looking, on the surface, like a React state bug.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Task 48: the dev-mode route indicator renders a <nextjs-portal> overlay that grabs
  // keyboard focus with no visible focus ring of its own (its ring lives inside a shadow
  // root, invisible to getComputedStyle on the host element) -- E2E runs against `next dev`
  // (playwright.config.ts's webServer), so left on this dev-only overlay would make the
  // a11y.spec.ts tab-sweep both flaky and, when it lands on the portal, a false failure
  // against chrome that never ships to a visitor.
  devIndicators: false,
};

export default nextConfig;
