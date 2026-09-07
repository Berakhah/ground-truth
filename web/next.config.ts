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
};

export default nextConfig;
