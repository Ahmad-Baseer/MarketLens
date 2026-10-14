import Link from "next/link";
import type { ReactNode } from "react";
import type { Tone } from "@/lib/format";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl border border-line bg-surface shadow-card ${className}`}>{children}</div>
  );
}

export function Section({
  title,
  subtitle,
  action,
  children,
  id,
  flush = false,
}: {
  title: string;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  id?: string;
  /** no top margin, e.g. inside a grid column */
  flush?: boolean;
}) {
  return (
    <section id={id} className={`${flush ? "" : "mt-12"} scroll-mt-20`}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-sm text-ink-2">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

const TONES: Record<Tone, string> = {
  gain: "bg-gain-soft text-gain",
  loss: "bg-loss-soft text-loss",
  warn: "bg-warn-soft text-warn",
  info: "bg-info-soft text-info",
  brand: "bg-brand-soft text-brand",
  muted: "bg-surface-2 text-ink-2",
};

export function Badge({ tone = "muted", children, className = "" }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function Stat({
  label,
  value,
  hint,
  valueClass = "",
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  valueClass?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</div>
      <div className={`num mt-1 text-xl font-semibold tracking-tight text-ink ${valueClass}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-2">{hint}</div>}
    </div>
  );
}

export function TextLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="text-sm font-medium text-brand hover:text-brand-2 hover:underline">
      {children}
    </Link>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <Card className="px-6 py-10 text-center">
      <div className="text-base font-semibold text-ink">{title}</div>
      {children && <div className="mx-auto mt-2 max-w-xl text-sm text-ink-2">{children}</div>}
    </Card>
  );
}

/** A horizontally scrollable table wrapper, so wide tables never push the page sideways on phones. */
export function TableWrap({ children }: { children: ReactNode }) {
  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">{children}</div>
    </Card>
  );
}

export const th = "px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-ink-3 whitespace-nowrap";
export const td = "px-4 py-3 text-sm text-ink whitespace-nowrap";
