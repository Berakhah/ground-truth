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

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable}`}>
      <body>{children}</body>
    </html>
  );
}
