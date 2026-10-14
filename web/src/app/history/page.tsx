import type { Metadata } from "next";
import Link from "next/link";
import { ProfitCurve } from "@/components/charts";
import { SignalLine } from "@/components/signals";
import { Card, Empty, Section, Stat, TableWrap, td, th } from "@/components/ui";
import { getHistoryIndex, getHistoryYear } from "@/lib/data";
import { fmtDay, fmtNum, fmtPct, fmtRs, onStake, tone } from "@/lib/format";
import type { SignalCard } from "@/lib/types";

export const revalidate = 300;
export const metadata: Metadata = { title: "History" };

const FILTERS = {
  all: { label: "All", test: () => true },
  won: { label: "Won", test: (c: SignalCard) => c.result?.status === "closed" && (c.result.net ?? 0) > 0 },
  lost: { label: "Lost", test: (c: SignalCard) => c.result?.status === "closed" && (c.result.net ?? 0) <= 0 },
  stops: { label: "Stop hit", test: (c: SignalCard) => !!c.result?.outcome?.startsWith("stop") },
  skipped: { label: "Skipped", test: (c: SignalCard) => c.result?.status === "skipped" },
} as const;
type FilterKey = keyof typeof FILTERS;

type Props = { searchParams: Promise<{ year?: string; show?: string }> };

export default async function HistoryPage({ searchParams }: Props) {
  const sp = await searchParams;
  const idx = await getHistoryIndex();
  if (!idx || !idx.years.length) return <Empty title="No history yet" />;
  const year = sp.year && idx.years.includes(+sp.year) ? +sp.year : idx.years[0];
  const show: FilterKey = sp.show && sp.show in FILTERS ? (sp.show as FilterKey) : "all";
  const hy = await getHistoryYear(year);
  const tr = idx.track_record.DIV_K5;
  const last = idx.curve.at(-1);
  const href = (y: number, f: FilterKey) => `/history?year=${y}${f === "all" ? "" : `&show=${f}`}`;

  const weeks = (hy?.weeks ?? [])
    .map((w) => ({ ...w, shown: w.signals.filter(FILTERS[show].test) }))
    .filter((w) => w.shown.length);

  return (
    <>
      <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">History</h1>
      <p className="mt-2 max-w-3xl text-ink-2">
        Every dividend run-up signal since 2018 and what happened to it. Until the live record began, these are the
        engine replayed day by day, seeing only what was known each evening. Results are after 0.6% costs and 15%
        dividend tax. A stop hit means the lower limit was reached before the ex-date.
      </p>

      {tr && (
        <Card className="mt-6 p-5">
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-5">
            <Stat label="Signals" value={fmtNum(tr.all.n)} hint={`since ${fmtDay(tr.since, "month")}`} />
            <Stat label="Won" value={fmtPct(tr.all.win_rate, 0)} />
            <Stat label="Average" value={fmtPct(tr.all.mean_net, 2, true)} valueClass={tone(tr.all.mean_net)} />
            <Stat label="Stopped out" value={fmtPct(tr.all.stopped, 1)} />
            <Stat
              label="Rs 100k on every signal"
              value={last ? fmtRs(last.cum_profit, 0) : "—"}
              valueClass={tone(last?.cum_profit)}
              hint={last ? `total profit over ${fmtNum(last.trades)} trades` : undefined}
            />
          </div>
          <div className="mt-6">
            <ProfitCurve points={idx.curve} />
          </div>
          <p className="mt-2 text-xs text-ink-3">
            Cumulative profit if Rs 100,000 went into every signal (not compounded). Flat stretches are months with
            few announced dividends.
          </p>
        </Card>
      )}

      {tr?.by_year && (
        <Section title="By year">
          <TableWrap>
            <table className="w-full">
              <thead className="border-b border-line bg-surface-2/60">
                <tr>
                  <th className={th}>Year</th>
                  <th className={`${th} text-right`}>Signals</th>
                  <th className={`${th} text-right`}>Won</th>
                  <th className={`${th} text-right`}>Average</th>
                  <th className={`${th} text-right`}>Median</th>
                  <th className={`${th} text-right`}>Stops</th>
                  <th className={`${th} text-right`}>Rs 100k each</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {Object.entries(tr.by_year)
                  .sort(([a], [b]) => +b - +a)
                  .map(([y, v]) => (
                    <tr key={y} className="hover:bg-surface-2">
                      <td className={td}>
                        <Link href={href(+y, "all")} className="font-medium text-brand hover:underline">
                          {y}
                        </Link>
                      </td>
                      <td className={`${td} num text-right`}>{v.n}</td>
                      <td className={`${td} num text-right`}>{fmtPct(v.win_rate, 0)}</td>
                      <td className={`${td} num text-right font-semibold ${tone(v.mean_net)}`}>{fmtPct(v.mean_net, 2, true)}</td>
                      <td className={`${td} num text-right ${tone(v.median_net)}`}>{fmtPct(v.median_net, 2, true)}</td>
                      <td className={`${td} num text-right`}>{fmtPct(v.stopped, 0)}</td>
                      <td className={`${td} num text-right ${tone(v.mean_net)}`}>{fmtRs(onStake(v.mean_net * v.n), 0)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </TableWrap>
        </Section>
      )}

      <Section title={`Week by week, ${year}`}>
        <div className="flex flex-wrap items-center gap-2">
          <nav className="flex flex-wrap gap-1.5" aria-label="Year">
            {idx.years.map((y) => (
              <Link
                key={y}
                href={href(y, show)}
                aria-current={y === year ? "page" : undefined}
                className={`num rounded-lg px-3 py-1.5 text-sm font-medium ${
                  y === year ? "bg-ink text-bg" : "bg-surface text-ink-2 ring-1 ring-line hover:text-ink"
                }`}
              >
                {y}
              </Link>
            ))}
          </nav>
          <span className="mx-1 hidden h-5 w-px bg-line sm:block" aria-hidden />
          <nav className="flex flex-wrap gap-1.5" aria-label="Outcome">
            {(Object.keys(FILTERS) as FilterKey[]).map((f) => (
              <Link
                key={f}
                href={href(year, f)}
                aria-current={f === show ? "page" : undefined}
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  f === show ? "bg-brand-soft text-brand" : "text-ink-2 hover:bg-surface-2 hover:text-ink"
                }`}
              >
                {FILTERS[f].label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="mt-5 space-y-5">
          {weeks.length ? (
            weeks.map((w) => (
              <Card key={w.week} className="overflow-hidden">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line bg-surface-2/60 px-4 py-3">
                  <h3 className="text-sm font-semibold text-ink">Week of {fmtDay(w.week, "full")}</h3>
                  <div className="num flex flex-wrap gap-x-4 text-xs text-ink-2">
                    <span>{w.n} signal{w.n === 1 ? "" : "s"}</span>
                    {w.closed > 0 && <span>{w.wins} of {w.closed} won</span>}
                    {w.stops > 0 && <span className="text-loss">{w.stops} stopped</span>}
                    {w.skipped > 0 && <span>{w.skipped} skipped</span>}
                    {w.mean_net != null && (
                      <span className={`font-semibold ${tone(w.mean_net)}`}>avg {fmtPct(w.mean_net, 2, true)}</span>
                    )}
                  </div>
                </div>
                <div className="divide-y divide-line">
                  {w.shown.map((c) => (
                    <SignalLine key={c.id} c={c} hideBacktest />
                  ))}
                </div>
              </Card>
            ))
          ) : (
            <Empty title="Nothing matches this filter" />
          )}
        </div>
      </Section>
    </>
  );
}
