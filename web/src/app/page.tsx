import Link from "next/link";
import { Sparkline } from "@/components/charts";
import { SignalHero, SignalLine } from "@/components/signals";
import { Badge, Card, Empty, Section, Stat, TableWrap, TextLink, td, th } from "@/components/ui";
import { getToday } from "@/lib/data";
import { day, fmtDay, fmtNum, fmtPct, fmtRs, onStake, tone } from "@/lib/format";
import type { Today, Upcoming, Warning } from "@/lib/types";

export const revalidate = 300;

export default async function Home() {
  const t = await getToday();
  if (!t) {
    return (
      <Empty title="No data yet">
        The evening job hasn&apos;t produced any signals yet. Run <code>mbf signals</code> after the data is loaded.
      </Empty>
    );
  }
  const top = t.tonight.filter((c) => c.strongest);
  const more = t.tonight.filter((c) => !c.strongest);
  const preview = t.tonight.some((c) => c.mode === "preview");
  const nextUp = t.upcoming.find((u) => u.qualifies_now);
  const tr = t.track_record.DIV_K5;

  return (
    <>
      <Header t={t} preview={preview} />

      {top.length ? (
        <div className="mt-6 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {top.map((c) => (
            <SignalHero key={c.id} c={c} />
          ))}
        </div>
      ) : (
        <div className="mt-6">
          <Empty title={`No signal qualifies for ${fmtDay(t.next_session)}`}>
            Signals only appear when a liquid stock&apos;s announced cash dividend is worth 2–7% of its price, five
            sessions before the ex-date. Most days have none; they cluster around results seasons.
            {nextUp && (
              <>
                {" "}
                Next on the calendar: <b>{nextUp.symbol}</b>, decided on the evening of{" "}
                {fmtDay(nextUp.signal_evening)}.
              </>
            )}
          </Empty>
        </div>
      )}

      {more.length > 0 && (
        <Section title="Also qualifying" subtitle="Ranked below the top three by their yield band's track record.">
          <Card className="divide-y divide-line overflow-hidden">
            {more.map((c) => (
              <SignalLine key={c.id} c={c} showResult={false} />
            ))}
          </Card>
        </Section>
      )}

      <div className="mt-12 grid items-start gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <OpenPositions t={t} />
        </div>
        <Section flush title="Market" subtitle="Context, not a signal input.">
          <div className="flex flex-col gap-5">
            <MarketCard t={t} />
            {tr && (
              <Card className="p-5">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-ink">Track record since {day(tr.since)?.getUTCFullYear()}</h3>
                  <TextLink href="/history">History →</TextLink>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-4">
                  <Stat label="Signals" value={fmtNum(tr.all.n)} />
                  <Stat label="Won" value={fmtPct(tr.all.win_rate, 0)} />
                  <Stat
                    label="Average"
                    value={fmtPct(tr.all.mean_net, 2, true)}
                    valueClass={tone(tr.all.mean_net)}
                    hint={`≈ ${fmtRs(onStake(tr.all.mean_net), 0)} per Rs 100k`}
                  />
                  <Stat label="Stopped out" value={fmtPct(tr.all.stopped, 1)} hint="protective stop hit" />
                </div>
              </Card>
            )}
          </div>
        </Section>
      </div>

      <UpcomingCalendar items={t.upcoming} />
      <Warnings items={t.warnings} />
    </>
  );
}

function Header({ t, preview }: { t: Today & { age_days: number }; preview: boolean }) {
  // a weekend plus a holiday is 4 days; anything older means the evening job isn't running
  const stale = t.age_days > 4;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
        <span>Published after the close of {fmtDay(t.asof, "full")}</span>
        {preview && <Badge tone="warn">Preview: the live record hasn&apos;t started</Badge>}
        {stale && <Badge tone="loss">Data may be out of date</Badge>}
      </div>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
        Signals for {fmtDay(t.next_session, "full")}
      </h1>
      <p className="mt-2 max-w-3xl text-ink-2">
        Buy in the last 30 minutes of the session (PSX&apos;s close is the average price of the last half hour) and
        sell at the ex-date&apos;s opening auction: the dividend is yours. Each signal shows the most you should pay
        and a protective stop.
      </p>
    </div>
  );
}

function OpenPositions({ t }: { t: Today }) {
  const replay = t.active.some((c) => c.mode !== "live");
  return (
    <Section flush title="Open positions" subtitle="Earlier signals still before their ex-date.">
      {t.active.length ? (
        <>
          <Card className="divide-y divide-line overflow-hidden">
            {t.active.map((c) => (
              <SignalLine key={c.id} c={c} />
            ))}
          </Card>
          {replay && (
            <p className="mt-2 text-xs text-ink-3">
              Until the live record starts, open positions come from the engine&apos;s replay (marked Backtest).
            </p>
          )}
        </>
      ) : (
        <Empty title="Nothing open right now" />
      )}
    </Section>
  );
}

function MarketCard({ t }: { t: Today }) {
  const m = t.market;
  if (!m.kse100) return null;
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">KSE-100</h3>
          <div className="num mt-1 text-2xl font-semibold tracking-tight text-ink">{fmtNum(m.kse100, 0)}</div>
          <div className={`num text-sm ${tone(m.chg_1d)}`}>{fmtPct(m.chg_1d, 2, true)} today</div>
        </div>
        {m.spark && <Sparkline values={m.spark.map((p) => p.close)} className="h-12 w-32" />}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4">
        <Stat label="5 days" value={fmtPct(m.chg_5d, 1, true)} valueClass={`text-base ${tone(m.chg_5d)}`} />
        <Stat label="20 days" value={fmtPct(m.chg_20d, 1, true)} valueClass={`text-base ${tone(m.chg_20d)}`} />
      </div>
      <p className="mt-4 text-xs leading-relaxed text-ink-2">
        {m.above_200d === false ? "Below" : m.above_200d ? "Above" : "Near"} its 200-day average.{" "}
        {m.breadth50 != null && <>{fmtPct(m.breadth50, 0)} of liquid stocks are above their 50-day average. </>}
        Context only: the market trend didn&apos;t change how the dividend run-up performed.
      </p>
    </Card>
  );
}

function UpcomingCalendar({ items }: { items: Upcoming[] }) {
  return (
    <Section
      id="calendar"
      title="Upcoming"
      subtitle="Announced cash dividends whose run-up window opens in the next three weeks. Whether each one becomes a signal is decided on the evening shown, at that day's price."
    >
      {items.length ? (
        <TableWrap>
          <table className="w-full">
            <thead className="border-b border-line bg-surface-2/60">
              <tr>
                <th className={th}>Stock</th>
                <th className={th}>Decided on</th>
                <th className={th}>Ex-date</th>
                <th className={`${th} text-right`}>Dividend</th>
                <th className={`${th} text-right`}>Yield now</th>
                <th className={th}>Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {items.map((u) => (
                <tr key={u.symbol + u.ex_date}>
                  <td className={td}>
                    <div className="font-semibold">{u.symbol}</div>
                    <div className="max-w-56 truncate text-xs text-ink-2">{u.name}</div>
                  </td>
                  <td className={`${td} num`}>{fmtDay(u.signal_evening)}</td>
                  <td className={`${td} num`}>{fmtDay(u.ex_date)}</td>
                  <td className={`${td} num text-right`}>{fmtRs(u.dividend_rs)}</td>
                  <td className={`${td} num text-right`}>{fmtPct(u.yield_now, 1)}</td>
                  <td className={td}>
                    {u.qualifies_now ? (
                      <Badge tone="gain">Would qualify today</Badge>
                    ) : !u.liquid ? (
                      <Badge>Not liquid enough</Badge>
                    ) : (
                      <Badge>Yield outside 2–7%</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      ) : (
        <Empty title="No announced dividends in the window">
          New announcements are picked up every evening, mostly during results seasons.
        </Empty>
      )}
    </Section>
  );
}

function Warnings({ items }: { items: Warning[] }) {
  const groups = new Map<string, Warning[]>();
  for (const w of items) groups.set(w.warning, [...(groups.get(w.warning) ?? []), w]);
  return (
    <Section
      id="warnings"
      title="Warnings"
      subtitle="Situations where buying has reliably done worse than comparable stocks. Flags on the 200 most-traded stocks, after today's close."
    >
      {groups.size ? (
        <div className="grid gap-4 md:grid-cols-2">
          {[...groups.entries()].map(([k, ws]) => (
            <Card key={k} className="p-5">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-warn-soft text-warn" aria-hidden>
                  <svg viewBox="0 0 16 16" className="h-3.5 w-3.5">
                    <path d="M8 1.5l7 12.5H1z" className="fill-current" />
                  </svg>
                </span>
                <h3 className="text-sm font-semibold text-ink">{ws[0].title}</h3>
                <span className="num text-xs text-ink-3">{ws.length}</span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-ink-2">{ws[0].detail}</p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {ws.map((w) => (
                  <span
                    key={w.symbol}
                    title={w.name ?? undefined}
                    className="rounded-md border border-line bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink"
                  >
                    {w.symbol}
                  </span>
                ))}
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Empty title="No warnings on liquid stocks today" />
      )}
      <p className="mt-3 text-xs text-ink-3">
        Warnings never create trades. <Link href="/how-it-works#warnings" className="underline">How they were tested</Link>.
      </p>
    </Section>
  );
}
