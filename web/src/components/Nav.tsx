"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Today" },
  { href: "/history", label: "History" },
  { href: "/how-it-works", label: "How it works" },
];

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5" aria-label="MarketLens home">
      <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden>
        <rect width="32" height="32" rx="9" className="fill-brand" />
        <circle cx="14" cy="14" r="7" fill="none" strokeWidth="2.5" className="stroke-surface" />
        <path d="M19 19l6 6" strokeWidth="2.75" strokeLinecap="round" className="stroke-surface" />
        <path d="M10.5 16l2.5-2.5 2 2 3-3.5" fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="stroke-surface" />
      </svg>
      <span className="text-[17px] font-semibold tracking-tight text-ink">
        Market<span className="text-brand">Lens</span>
      </span>
    </Link>
  );
}

export function Nav() {
  const path = usePathname();
  return (
    <nav className="flex items-center gap-1 text-sm">
      {LINKS.map((l) => {
        const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
              active ? "bg-brand-soft text-brand" : "text-ink-2 hover:bg-surface-2 hover:text-ink"
            }`}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
