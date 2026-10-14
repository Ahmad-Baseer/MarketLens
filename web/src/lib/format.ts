import type { Result, SignalCard } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Pipeline dates are Pakistan-local calendar days; never let a browser timezone shift them. */
export function day(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : null;
}

export function fmtDay(iso: string | null | undefined, style: "short" | "long" | "full" | "month" = "short") {
  const d = day(iso);
  if (!d) return "—";
  const dd = d.getUTCDate(), mon = MONTHS[d.getUTCMonth()], y = d.getUTCFullYear(), wd = DAYS[d.getUTCDay()];
  if (style === "short") return `${wd} ${dd} ${mon}`;
  if (style === "long") return `${dd} ${mon} ${y}`;
  if (style === "month") return `${mon} ${y}`;
  return `${wd} ${dd} ${mon} ${y}`;
}

export function fmtTime(iso: string | null | undefined) {
  const m = iso ? /T(\d{2}):(\d{2})/.exec(iso) : null;
  if (!m) return "";
  const h = +m[1];
  return `${((h + 11) % 12) + 1}:${m[2]} ${h < 12 ? "am" : "pm"}`;
}

const num = (n: number, digits: number) =>
  n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export function fmtRs(n: number | null | undefined, digits = 2) {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n < 0 ? "−" : ""}Rs ${num(Math.abs(n), digits)}`;
}

export function fmtNum(n: number | null | undefined, digits = 0) {
  return n == null || !Number.isFinite(n) ? "—" : num(n, digits);
}

export function fmtPct(n: number | null | undefined, digits = 1, signed = false) {
  if (n == null || !Number.isFinite(n)) return "—";
  const v = num(Math.abs(n) * 100, digits);
  return `${n < 0 ? "−" : signed && n > 0 ? "+" : ""}${v}%`;
}

/** Rs 45.2m, Rs 1.3bn — for turnover and index-sized numbers. */
export function fmtRsCompact(n: number | null | undefined) {
  if (n == null || !Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  if (a >= 1e9) return `${sign}Rs ${num(a / 1e9, 1)}bn`;
  if (a >= 1e6) return `${sign}Rs ${num(a / 1e6, 1)}m`;
  if (a >= 1e3) return `${sign}Rs ${num(a / 1e3, 0)}k`;
  return `${sign}Rs ${num(a, 0)}`;
}

export const tone = (n: number | null | undefined) =>
  n == null || !Number.isFinite(n) || n === 0 ? "text-ink-2" : n > 0 ? "text-gain" : "text-loss";

export type Tone = "gain" | "loss" | "warn" | "info" | "muted" | "brand";

export function outcome(r: Result | undefined): { label: string; tone: Tone; short: string } {
  if (!r) return { label: "Not tracked", short: "—", tone: "muted" };
  switch (r.status) {
    case "pending_entry":
      return { label: "Waiting for the entry day", short: "Pending", tone: "info" };
    case "open":
      return { label: "Holding until the ex-date", short: "Open", tone: "info" };
    case "skipped":
      return { label: r.outcome_text ?? "Skipped: entry conditions not met", short: "Skipped", tone: "muted" };
    case "closed":
      if (r.outcome?.startsWith("stop"))
        return { label: r.outcome_text ?? "Protective stop hit", short: "Stop hit", tone: "loss" };
      return {
        label: r.outcome_text ?? "Sold at the ex-date",
        short: (r.net ?? 0) > 0 ? "Won" : "Lost",
        tone: (r.net ?? 0) > 0 ? "gain" : "loss",
      };
    default:
      return { label: "No price data", short: "—", tone: "muted" };
  }
}

export const modeLabel: Record<SignalCard["mode"], string> = {
  live: "Live",
  backtest: "Backtest",
  preview: "Preview",
};

/** Profit in rupees on a stake (default Rs 100,000). */
export const onStake = (net: number | null | undefined, stake = 100_000) =>
  net == null || !Number.isFinite(net) ? null : net * stake;
