import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Logo, Nav } from "@/components/Nav";
import "./globals.css";

const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "MarketLens: PSX dividend run-up signals", template: "%s · MarketLens" },
  description:
    "Evidence-tested short-term signals for Pakistan Stock Exchange stocks, with a full, honest track record.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f5f6f8" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0e13" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${sans.variable} ${mono.variable} min-h-dvh antialiased`}>
        <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
            <Logo />
            <Nav />
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 pb-20 pt-8 sm:px-6">{children}</main>
        <footer className="border-t border-line">
          <div className="mx-auto max-w-6xl px-4 py-8 text-xs leading-relaxed text-ink-3 sm:px-6">
            <p>
              Research signals, not investment advice. Results describe the past and trades can lose money. Prices
              are PSX official closes and opening-auction prints; 0.6% round-trip costs and 15% dividend tax are
              already deducted. Data: PSX Data Portal.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
