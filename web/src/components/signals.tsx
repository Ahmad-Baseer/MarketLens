import Link from "next/link";
import type { SignalCard } from "@/lib/types";
import { fmtDay, fmtPct, fmtRs, modeLabel, onStake, outcome, tone } from "@/lib/format";
import { Badge, Card } from "./ui";

export function ModeBadge({ mode }: { mode: SignalCard["mode"] }) {
  const t = mode === "live" ? "brand" : mode === "preview" ? "warn" : "muted";
  const title =
    mode === "live"
      ? "Published on the evening shown and recorded permanently"
      : mode === "preview"
        ? "Computed by the engine, not yet written to the live record"
        : "What the engine would have published, replayed with only the information available that day";
  return (
    <Badge tone={t}>
      <span title={title}>{modeLabel[mode]}</span>
    </Badge>
  );
}

export function OutcomeBadge({ c }: { c: SignalCard }) {
  const o = outcome(c.result);
  return <Badge tone={o.tone}>{o.short}</Badge>;
}

export function WarningChips({ c }: { c: SignalCard }) {
  if (!c.warnings?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {c.warnings.map((w) => (
        <Badge key={w.warning} tone="warn">
          <svg viewBox="0 0 16 16" className="h-3 w-3" aria-hidden>
            <path d="M8 1.5l7 12.5H1z" className="fill-current" />
          </svg>
          {w.title}
        </Badge>
      ))}
    </div>
  );
}

function Row({ k, v, strong = false }: { k: string; v: React.ReactNode; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
      <dt className="text-ink-2">{k}</dt>
      <dd className={`num text-right ${strong ? "font-semibold text-ink" : "text-ink"}`}>{v}</dd>
    </div>
  );
}

/** The home page's big card: one signal, everything needed to act on it. */
export function SignalHero({ c }: { c: SignalCard }) {
  const e = c.expected;
  return (
    <Card className="group relative flex flex-col overflow-hidden transition-shadow hover:shadow-lg">
      <div className="absolute inset-x-0 top-0 h-1 bg-brand" aria-hidden />
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {c.rank != null && (
              <span className="num flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">
                {c.rank}
              </span>
            )}
            <span className="text-xl font-semibold tracking-tight text-ink">{c.symbol}</span>
            <ModeBadge mode={c.mode} />
          </div>
          <div className="mt-1 truncate text-sm text-ink-2" title={c.name ?? undefined}>
            {c.name}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="num text-2xl font-semibold tracking-tight text-brand">{fmtPct(c.yield, 1)}</div>
          <div className="text-xs text-ink-3">dividend yield</div>
        </div>
      </div>

      <dl className="mx-5 mt-4 divide-y divide-line border-y border-line">
        <Row k="Buy" v={<>last 30 min of <b>{fmtDay(c.entry_date)}</b></>} />
        <Row k="Pay at most" v={fmtRs(c.max_entry_price)} strong />
        <Row k="Sell" v={<>opening auction <b>{fmtDay(c.exit_date)}</b></>} />
        <Row k="Dividend" v={`${fmtRs(c.dividend_rs)} per share`} />
        <Row k="Protective stop" v={`${fmtPct(c.stop_pct, 1)} below entry`} />
      </dl>

      <div className="px-5 py-4">
        <div className="text-xs font-medium uppercase tracking-wide text-ink-3">
          Past signals in the {c.yield_band} band
        </div>
        <div className="mt-1.5 flex items-baseline gap-4">
          <span className="num text-sm text-ink">
            <b className="text-base">{fmtPct(e.win_rate, 0)}</b> won
          </span>
          <span className={`num text-sm ${tone(e.mean_net)}`}>
            <b className="text-base">{fmtPct(e.mean_net, 2, true)}</b> avg
          </span>
          <span className="num text-xs text-ink-3">n = {e.n ?? "—"}</span>
        </div>
        <div className="num mt-1 text-xs text-ink-2">
          ≈ {fmtRs(onStake(e.mean_net), 0)} per Rs 100,000, after costs and tax
        </div>
        {c.warnings?.length ? (
          <div className="mt-3">
            <WarningChips c={c} />
          </div>
        ) : null}
      </div>

      <Link
        href={`/signals/${c.id}`}
        className="mt-auto flex items-center justify-between border-t border-line px-5 py-3 text-sm font-medium text-brand transition-colors hover:bg-brand-soft"
      >
        Why this signal
        <span aria-hidden className="transition-transform group-hover:translate-x-0.5">→</span>
      </Link>
    </Card>
  );
}

/** Compact one-line signal, for lists beyond the top three and for history. */
export function SignalLine({
  c,
  showResult = true,
  hideBacktest = false,
}: {
  c: SignalCard;
  showResult?: boolean;
  hideBacktest?: boolean;
}) {
  const r = c.result;
  const net = r?.net ?? null;
  return (
    <Link
      href={`/signals/${c.id}`}
      className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 px-4 py-3 transition-colors hover:bg-surface-2 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_auto]"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-ink">{c.symbol}</span>
          <span className="num text-xs text-ink-3">{fmtPct(c.yield, 1)} yield</span>
          {c.mode !== "live" && !(hideBacktest && c.mode === "backtest") && <ModeBadge mode={c.mode} />}
        </div>
        <div className="truncate text-xs text-ink-2">{c.name}</div>
      </div>
      <div className="num hidden text-sm text-ink-2 sm:block">
        {fmtDay(c.entry_date)} → {fmtDay(c.exit_date)}
      </div>
      <div className="num hidden text-sm sm:block">
        {r?.entry_price != null ? (
          <span className="text-ink-2">
            {fmtRs(r.entry_price)} → {r.exit_price != null ? fmtRs(r.exit_price) : r.last_price != null ? fmtRs(r.last_price) : "—"}
          </span>
        ) : (
          <span className="text-ink-3">{outcome(r).label}</span>
        )}
      </div>
      <div className="flex items-center justify-end gap-2">
        {showResult && net != null && (
          <span className={`num text-sm font-semibold ${tone(net)}`}>{fmtPct(net, 2, true)}</span>
        )}
        <OutcomeBadge c={c} />
      </div>
    </Link>
  );
}
