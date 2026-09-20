import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
// Print-only rules (@media print inside the file itself) -- imported unconditionally
// so every route gets the same print treatment without a per-page import.
import "./print.css";

// Self-hosted fonts (web/public/fonts/), NOT next/font/google -- see CLAUDE.md's
// security-hardening direction to forbid the Google Fonts CDN from day one.
// Both are variable fonts (a single file spans the whole weight range) and both
// ship their OFL.txt alongside the binary in public/fonts/.
const serif = localFont({
  src: "../public/fonts/Newsreader-Variable.ttf",
  variable: "--font-serif",
  weight: "200 800",
  style: "normal",
  display: "swap",
});

const sans = localFont({
  src: "../public/fonts/Inter-Variable.ttf",
  variable: "--font-sans",
  weight: "100 900",
  style: "normal",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Ground Truth — Leaderboard",
  description:
    "Pay-application and invoice field-extraction accuracy: a published methodology and a number you can reproduce.",
};

// GitHub Pages serves this as a static site and cannot set response headers, so the CSP has
// to be a <meta http-equiv> tag in <head> rather than a real Content-Security-Policy header
// (00 SS5.2 / security baseline, Task 52 item 7). The whole site is self-contained -- no
// external scripts, styles, images, fonts, or API calls -- so every directive below is
// `'self'`-only except two `'unsafe-inline'`s that Next.js's static export leaves no way
// around: it embeds its own RSC hydration payload as inline <script> tags and its
// critical-path CSS as inline <style>, with no per-request server to hand out a nonce. Both
// gaps are Next.js's own inline bootstrap, not third-party or user-controlled content -- there
// is no template injection point here, so `'unsafe-inline'` does not reopen an XSS the rest of
// this CSP was meant to close.
// `next dev` (used by local dev and by the Playwright e2e/a11y suite, playwright.config.ts)
// genuinely needs 'unsafe-eval' for React Fast Refresh -- it is a dev-server-only mechanism
// that never ships in `next build`'s static export, so scoping it to non-production keeps
// the deployed CSP exactly as strict as the comment above describes.
const SCRIPT_SRC =
  process.env.NODE_ENV === "production"
    ? "script-src 'self' 'unsafe-inline'"
    : "script-src 'self' 'unsafe-inline' 'unsafe-eval'";

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  SCRIPT_SRC,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable}`}>
      <head>
        <meta httpEquiv="Content-Security-Policy" content={CONTENT_SECURITY_POLICY} />
      </head>
      <body>{children}</body>
    </html>
  );
}
