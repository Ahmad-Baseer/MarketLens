import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Bars, CandleChart } from "@/components/charts";
import { ModeBadge, OutcomeBadge } from "@/components/signals";
import { Badge, Card, Section, Stat, TableWrap, td, th } from "@/components/ui";
import { getSignal } from "@/lib/data";
import { fmtDay, fmtNum, fmtPct, fmtRs, fmtRsCompact, fmtTime, onStake, outcome, tone } from "@/lib/format";
import type { SignalDetail } from "@/lib/types";

export const revalidate = 300;

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const s = await getSignal((await params).id);
  return { title: s ? `${s.symbol} ${s.type_name}, ${fmtDay(s.entry_date, "long")}` : "Signal not found" };
}

export default async function SignalPage({ params }: Props) {
  const s = await getSignal((await params).id);
  if (!s) notFound();
  const r = s.result;
  const entry = r?.entry_price ?? null;
  const stop = entry != null ? entry * (1 - s.stop_pct) : s.stop_price_approx;
  const exitPx = r?.exit_price ?? null;

  return (
    <article>
      <Link href={s.mode === "backtest" ? "/history" : "/"} className="text-sm text-ink-2 hover:text-ink">
        ← {s.mode === "backtest" ? "History" : "Today"}
      </Link>

      <header className="mt-4 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">{s.symbol}</h1>
            <Badge tone="brand">{s.type_name}</Badge>
            <ModeBadge mode={s.mode} />
            <OutcomeBadge c={s} />
          </div>
          <p className="mt-1 text-ink-2">
            {s.name}
            {s.sector && <span className="text-ink-3"> · {s.sector.toLowerCase()}</span>}
          </p>
        </div>
        <div className="text-right">
          <div className="num text-3xl font-semibold tracking-tight text-brand">{fmtPct(s.yield, 2)}</div>
          <div className="text-xs text-ink-3">dividend yield at the signal close</div>
        </div>
      </header>

      {s.mode === "backtest" && (
        <p className="mt-4 rounded-xl border border-line bg-surface-2 px-4 py-3 text-sm text-ink-2">
          This is a <b>backtest</b> signal: what the engine would have published on {fmtDay(s.signal_date, "full")},
          using only the information available that evening. It was not published live.
        </p>
      )}

      <div className="mt-6 grid items-start gap-5 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-ink">Price around the trade</h2>
            <Legend />
          </div>
          <div className="mt-3">
            <CandleChart
              prices={s.prices}
              band={{ from: s.entry_date, to: s.exit_date, label: "Holding" }}
              lines={[
                { price: s.max_entry_price, label: "Max buy", kind: "limit" },
                { price: stop, label: "Stop", kind: "stop" },
              ]}
              markers={[
                ...(entry != null ? [{ date: s.entry_date, label: "Buy", price: entry, kind: "buy" as const }] : []),
                ...(exitPx != null && r?.exit_date
                  ? [{ date: r.exit_date, label: r.outcome?.startsWith("stop") ? "Stop" : "Sell", price: exitPx, kind: (r.outcome?.startsWith("stop") ? "stop" : "sell") as "stop" | "sell" }]
                  : []),
              ]}
            />
          </div>
          <p className="mt-2 text-xs text-ink-3">
            Daily prices as traded (not adjusted). On the ex-date the price drops by roughly the dividend, which you
            keep.
          </p>
        </Card>

        <div className="flex flex-col gap-5">
          <PlanCard s={s} stop={stop} />
          <ResultCard s={s} />
        </div>
      </div>

      <Section title="Why this signal">
        <Card className="p-5">
          <ol className="space-y-3">
            {s.why.map((w, i) => (
              <li key={i} className="flex gap-3 text-sm leading-relaxed text-ink">
                <span className="num mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[11px] font-semibold text-brand">
                  {i + 1}
                </span>
                <span>{w}</span>
              </li>
            ))}
          </ol>
          {s.warnings_detail.length > 0 && (
            <div className="mt-5 space-y-2 border-t border-line pt-4">
              {s.warnings_detail.map((w) => (
                <div key={w.warning} className="rounded-xl bg-warn-soft px-4 py-3 text-sm">
                  <div className="font-semibold text-warn">{w.title}</div>
                  <div className="mt-0.5 text-ink-2">{w.detail}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </Section>

      <div className="grid gap-5 lg:grid-cols-2">
        <TrackRecord s={s} />
        <Context s={s} />
      </div>

      <PastSignals s={s} />
      <EventFacts s={s} />
    </article>
  );
}

function Legend() {
  const item = (cls: string, label: string, dashed = false) => (
    <span className="flex items-center gap-1.5">
      {dashed ? (
        <span className={`inline-block w-4 border-t-2 border-dashed ${cls}`} />
      ) : (
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${cls}`} />
      )}
      {label}
    </span>
  );
  return (
    <div className="flex flex-wrap gap-3 text-xs text-ink-2">
      {item("bg-brand", "Buy")}
      {item("bg-info", "Sell")}
      {item("border-loss", "Stop", true)}
      {item("border-ink-3", "Max buy", true)}
    </div>
  );
}

function PlanCard({ s, stop }: { s: SignalDetail; stop: number }) {
  const rows: [string, React.ReactNode][] = [
    ["Signal published", `${fmtDay(s.signal_date)}, after the close`],
    ["Buy", <>last 30 min, <b>{fmtDay(s.entry_date)}</b></>],
    ["Pay at most", <b key="m">{fmtRs(s.max_entry_price)}</b>],
    ["Sell", <>opening auction, <b>{fmtDay(s.exit_date)}</b></>],
    ["Holding", `${s.nights} nights`],
    ["Dividend", `${fmtRs(s.dividend_rs)} (${fmtNum(s.dividend_pct_of_par, 1)}% of Rs ${fmtNum(s.par, 0)} par)`],
    ["Protective stop", `${fmtRs(stop)} (${fmtPct(s.stop_pct, 1)} below entry)`],
  ];
  return (
    <Card className="p-5">
      <h2 className="text-sm font-semibold text-ink">The plan</h2>
      <dl className="mt-3 divide-y divide-line">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3 py-2 text-sm">
            <dt className="text-ink-2">{k}</dt>
            <dd className="num text-right text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs leading-relaxed text-ink-3">
        Skip the trade if the stock is locked at its upper circuit, or if it&apos;s already above the maximum price
        by the close.
      </p>
    </Card>
  );
}

function ResultCard({ s }: { s: SignalDetail }) {
  const r = s.result;
  const o = outcome(r);
  if (!r) return null;
  const toneCls = { gain: "border-gain/40", loss: "border-loss/40", info: "border-info/40", warn: "border-warn/40", muted: "border-line", brand: "border-brand/40" }[o.tone];
  return (
    <Card className={`p-5 ${toneCls}`}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ink">What happened</h2>
        <OutcomeBadge c={s} />
      </div>
      <p className="mt-2 text-sm text-ink-2">{o.label}</p>
      {r.entry_price != null && (
        <div className="mt-4 grid grid-cols-2 gap-4">
          <Stat label="Bought at" value={fmtRs(r.entry_price)} valueClass="text-base" />
          {r.status === "closed" ? (
            <Stat label="Sold at" value={fmtRs(r.exit_price)} hint={fmtDay(r.exit_date)} valueClass="text-base" />
          ) : (
            <Stat label="Last price" value={fmtRs(r.last_price)} valueClass="text-base" />
          )}
          {r.status === "closed" && (
            <Stat label="Dividend kept" value={r.dividend ? fmtRs(r.dividend * 0.85) : "—"} hint={r.dividend ? "per share, after 15% tax" : "sold before the ex-date"} valueClass="text-base" />
          )}
          <Stat
            label={r.status === "closed" ? "Net result" : "So far"}
            value={fmtPct(r.net, 2, true)}
            hint={`${fmtRs(onStake(r.net), 0)} per Rs 100,000`}
            valueClass={tone(r.net)}
          />
        </div>
      )}
    </Card>
  );
}

function TrackRecord({ s }: { s: SignalDetail }) {
  const tr = s.track_record;
  if (!tr) return null;
  const band = s.yield_band ? tr.by_band[s.yield_band] : null;
  const years = Object.entries(tr.by_year ?? {}).map(([y, v]) => ({ label: y, value: v.mean_net, sub: `n=${v.n}` }));
  return (
    <Section title="Track record" subtitle="Every signal of this type since 2018, after costs and dividend tax.">
      <Card className="p-5">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Signals" value={fmtNum(tr.all.n)} />
          <Stat label="Won" value={fmtPct(tr.all.win_rate, 0)} />
          <Stat label="Average" value={fmtPct(tr.all.mean_net, 2, true)} valueClass={tone(tr.all.mean_net)} />
          <Stat label="Median" value={fmtPct(tr.all.median_net, 2, true)} valueClass={tone(tr.all.median_net)} />
        </div>
        {band && (
          <p className="mt-4 rounded-xl bg-brand-soft px-4 py-3 text-sm text-ink">
            In this signal&apos;s <b>{s.yield_band}</b> yield band: {fmtNum(band.n)} signals, {fmtPct(band.win_rate, 0)} won,
            average <b className={tone(band.mean_net)}>{fmtPct(band.mean_net, 2, true)}</b>.
          </p>
        )}
        <div className="mt-5 text-xs font-medium uppercase tracking-wide text-ink-3">Average per signal, by year</div>
        <div className="mt-2">
          <Bars items={years} format={(v) => fmtPct(v, 1, true)} />
        </div>
      </Card>
    </Section>
  );
}

function Context({ s }: { s: SignalDetail }) {
  const t = s.technicals;
  const f = s.fundamentals;
  const pct = (v: number | null | undefined, signed = true) => fmtPct(v, 1, signed);
  const techRows: [string, string, string?][] = [
    ["vs 50-day average", pct(t.dma50), t.dma50 != null ? tone(t.dma50) : undefined],
    ["vs 200-day average", pct(t.dma200), t.dma200 != null ? tone(t.dma200) : undefined],
    ["Last 5 days", pct(t.r5), tone(t.r5)],
    ["Last 20 days", pct(t.r20), tone(t.r20)],
    ["From 52-week high", pct(t.off_hi250), undefined],
    ["RSI (14)", fmtNum(t.rsi14, 0)],
    ["Typical daily range (ATR)", pct(t.atr_pct, false)],
    ["Turnover rank", t.to_rank != null ? `#${fmtNum(t.to_rank)}` : "—"],
    ["Median daily turnover", fmtRsCompact(t.med_to20)],
  ];
  return (
    <Section title="Fundamentals and technicals" subtitle={`Technicals as of the signal close, ${fmtDay(s.technicals_date, "long")}.`}>
      <Card className="divide-y divide-line">
        {f?.eps_annual?.length ? (
          <div className="p-5">
            <div className="flex items-baseline justify-between">
              <div className="text-xs font-medium uppercase tracking-wide text-ink-3">Earnings per share, by year</div>
              <div className="text-xs text-ink-3">PSX, as of {fmtDay(f.as_of, "long")}</div>
            </div>
            <Bars items={f.eps_annual.slice(-5).map((e) => ({ label: e.period, value: e.eps }))} format={(v) => fmtNum(v, 2)} height={130} />
            <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-ink-2">
              {f.eps_growth_pct && (
                <span>
                  EPS growth {f.eps_growth_pct.period}:{" "}
                  <b className={tone(f.eps_growth_pct.value)}>{fmtNum(f.eps_growth_pct.value, 1)}%</b>
                </span>
              )}
              {f.net_margin_pct && (
                <span>
                  Net margin {f.net_margin_pct.period}: <b className="text-ink">{fmtNum(f.net_margin_pct.value, 1)}%</b>
                </span>
              )}
            </div>
          </div>
        ) : (
          <p className="p-5 text-sm text-ink-3">
            {s.mode === "backtest"
              ? "Fundamentals are shown only for recent signals, so an old signal never displays figures published after it."
              : "No fundamentals available for this company."}
          </p>
        )}
        <dl className="grid grid-cols-1 gap-x-8 p-5 sm:grid-cols-2">
          {techRows.map(([k, v, cls]) => (
            <div key={k} className="flex items-baseline justify-between gap-3 border-b border-line py-2 text-sm last:border-0 sm:[&:nth-last-child(2)]:border-0">
              <dt className="text-ink-2">{k}</dt>
              <dd className={`num ${cls ?? "text-ink"}`}>{v}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </Section>
  );
}

function PastSignals({ s }: { s: SignalDetail }) {
  if (!s.this_stock_before.length) return null;
  return (
    <Section title={`${s.symbol}'s earlier signals`} subtitle="The same trade on this stock's previous dividends.">
      <TableWrap>
        <table className="w-full">
          <thead className="border-b border-line bg-surface-2/60">
            <tr>
              <th className={th}>Signal</th>
              <th className={th}>Ex-date</th>
              <th className={`${th} text-right`}>Yield</th>
              <th className={th}>Outcome</th>
              <th className={`${th} text-right`}>Net</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {[...s.this_stock_before].reverse().map((p) => (
              <tr key={p.id} className="hover:bg-surface-2">
                <td className={td}>
                  <Link href={`/signals/${p.id}`} className="text-brand hover:underline">
                    {fmtDay(p.signal_date, "long")}
                  </Link>
                </td>
                <td className={`${td} num`}>{fmtDay(p.ex_date, "long")}</td>
                <td className={`${td} num text-right`}>{fmtPct(p.yield, 1)}</td>
                <td className={td}>
                  {p.outcome == null ? "—" : p.outcome.startsWith("stop") ? <Badge tone="loss">Stop hit</Badge> : <Badge>Sold at ex-date</Badge>}
                </td>
                <td className={`${td} num text-right font-semibold ${tone(p.net)}`}>{fmtPct(p.net, 2, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Section>
  );
}

function EventFacts({ s }: { s: SignalDetail }) {
  const e = s.event;
  const rows: [string, string][] = [
    ["Announced", `${fmtDay(e.announced_at, "full")}${fmtTime(e.announced_at) && e.source === "psx" ? `, ${fmtTime(e.announced_at)}` : ""}`],
    ["PSX entry", e.details ?? "—"],
    ["Book closure", e.book_closure[0] ? `${fmtDay(e.book_closure[0], "long")} – ${fmtDay(e.book_closure[1], "long")}` : "—"],
    ["Ex-date", `${fmtDay(e.ex_date, "full")} (${e.ex_basis === "book_closure" ? "predicted from the book closure" : "PSX's price adjustment"})`],
    ["Source", e.source === "psx" ? "PSX payout announcements" : "Historical payout record (AKD), dated to PSX's adjustment"],
  ];
  return (
    <Section title="The announcement">
      <Card className="p-5">
        <dl className="divide-y divide-line">
          {rows.map(([k, v]) => (
            <div key={k} className="grid grid-cols-1 gap-1 py-2 text-sm sm:grid-cols-[180px_1fr]">
              <dt className="text-ink-2">{k}</dt>
              <dd className="text-ink">{v}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </Section>
  );
}
