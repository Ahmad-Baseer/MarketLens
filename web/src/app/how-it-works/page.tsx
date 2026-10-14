import type { Metadata } from "next";
import Link from "next/link";
import { Card, Section, Stat, TableWrap, td, th } from "@/components/ui";
import { getHistoryIndex } from "@/lib/data";
import { fmtNum, fmtPct, fmtRs, onStake, tone } from "@/lib/format";

export const revalidate = 300;
export const metadata: Metadata = { title: "How it works" };

const STEPS = [
  {
    t: "A company announces a cash dividend",
    d: "PSX publishes it with the book-closure dates. The ex-date (the first day a buyer no longer gets the dividend) is one session before the book closure starts.",
  },
  {
    t: "The evening job checks it",
    d: "Is the dividend worth 2–7% of the price? Is the stock among the 200 most traded, so you can actually buy and sell it? Is there no bonus or rights issue attached?",
  },
  {
    t: "Five sessions before the ex-date, the signal is published",
    d: "After that day's close. It tells you the most you should pay, the stop, and the exact sell date.",
  },
  {
    t: "You buy near the next close, and sell at the ex-date's opening auction",
    d: "You keep the dividend (minus 15% withholding tax). The share price drops by roughly the dividend that morning, but the run-up before it is what makes the trade.",
  },
];

const REJECTED: [string, string][] = [
  ["Short-term reversal (buying the week's biggest losers)", "Real but too small: +0.14% per trade after costs."],
  ["Pullbacks in an uptrend, breakouts after a quiet spell", "Weak and inconsistent from year to year."],
  ["Run-up before results announcements", "Doesn't clear the 0.6% trading costs."],
  ["A 23-factor model combining technicals and fundamentals", "No better than its parts once tested out of sample."],
  ["Buying right after the dividend announcement (3-week hold)", "Replayed day by day it made +0.27% per trade, short of the bar."],
  ["Rights issues", "Gains only in illiquid stocks you can't really trade."],
  ["KSE-100, KSE-30 and KMI-30 index changes", "No reliable gain for additions; KMI-30 additions are promising but unproven."],
  ["Foreign and local investor flows (NCCPL)", "Flows follow the market rather than lead it."],
];

const WARNINGS: [string, string][] = [
  ["Just went ex-dividend", "Buying in the 3–5 sessions after an ex-date did 0.6–0.7% worse than comparable stocks, in at least 8 of 9 years."],
  ["Just reported a big earnings jump", "After a large year-on-year EPS beat, buyers did 0.4–0.7% worse over the next week: the news was already priced."],
  ["Closed at the day's low on a big drop", "Stocks closing in the bottom 15% of the day's range after a 3%+ fall kept falling overnight: 0.4% worse than comparable stocks."],
  ["Unusual volume (over 3× normal)", "0.2% worse than comparable stocks over the following week."],
  ["PSX unusual-movement notice", "Stocks PSX queried about unusual moves lagged comparable stocks (a weaker effect)."],
  ["Leaving the KSE-30 index", "1.3% worse than comparable stocks in the week after the notice, in 10 of 11 years."],
];

export default async function HowItWorks() {
  const idx = await getHistoryIndex();
  const tr = idx?.track_record.DIV_K5;

  return (
    <article className="max-w-4xl">
      <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">How it works</h1>
      <p className="mt-3 text-lg leading-relaxed text-ink-2">
        MarketLens publishes one kind of signal, because only one passed every test: the <b className="text-ink">dividend
        run-up</b>. Prices of PSX stocks with an announced cash dividend tend to rise in the days before the ex-date. Buy
        five sessions before, sell at the ex-date&apos;s opening auction, keep the dividend.
      </p>

      <Section title="The signal, step by step">
        <ol className="grid gap-4 sm:grid-cols-2">
          {STEPS.map((s, i) => (
            <Card key={s.t} className="p-5">
              <div className="num flex h-7 w-7 items-center justify-center rounded-full bg-brand text-sm font-semibold text-surface">
                {i + 1}
              </div>
              <h3 className="mt-3 font-semibold text-ink">{s.t}</h3>
              <p className="mt-1 text-sm leading-relaxed text-ink-2">{s.d}</p>
            </Card>
          ))}
        </ol>
      </Section>

      {tr && (
        <Section
          title="What to expect"
          subtitle={`Every signal since 2018, after 0.6% trading costs and 15% dividend tax. Backtest until the live record began.`}
        >
          <Card className="p-5">
            <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
              <Stat label="Signals" value={fmtNum(tr.all.n)} hint="about 65 a year" />
              <Stat label="Won" value={fmtPct(tr.all.win_rate, 0)} />
              <Stat label="Average" value={fmtPct(tr.all.mean_net, 2, true)} valueClass={tone(tr.all.mean_net)} hint={`≈ ${fmtRs(onStake(tr.all.mean_net), 0)} per Rs 100k`} />
              <Stat label="Worst single trade" value={fmtPct(tr.all.worst, 1, true)} valueClass="text-loss" />
            </div>
          </Card>
          <div className="mt-4">
            <TableWrap>
              <table className="w-full">
                <thead className="border-b border-line bg-surface-2/60">
                  <tr>
                    <th className={th}>Dividend yield</th>
                    <th className={`${th} text-right`}>Signals</th>
                    <th className={`${th} text-right`}>Won</th>
                    <th className={`${th} text-right`}>Average</th>
                    <th className={`${th} text-right`}>Per Rs 100k</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {Object.entries(tr.by_band).map(([b, v]) => (
                    <tr key={b}>
                      <td className={`${td} font-medium`}>{b}</td>
                      <td className={`${td} num text-right`}>{v.n}</td>
                      <td className={`${td} num text-right`}>{fmtPct(v.win_rate, 0)}</td>
                      <td className={`${td} num text-right font-semibold ${tone(v.mean_net)}`}>{fmtPct(v.mean_net, 2, true)}</td>
                      <td className={`${td} num text-right`}>{fmtRs(onStake(v.mean_net), 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          </div>
          <div className="mt-4 space-y-3 text-sm leading-relaxed text-ink-2">
            <p>
              About 4 in 10 signals lose. A typical winner makes around +2.3%, a typical loser around −2%; the protective
              stop is hit about 3% of the time and costs around 11% when it is. The edge is the average over many
              signals. Spread your money across them rather than betting heavily on one.
            </p>
            <p>
              The absolute result follows the market: 2018, 2020 and 2021 were slightly negative on average. Against
              comparable stocks held over exactly the same days, the signal was better in 8 of 9 years. Signals cluster
              in results seasons (March–April and September–October); most days there are none.
            </p>
          </div>
        </Section>
      )}

      <Section title="Placing the trades">
        <Card className="divide-y divide-line">
          {[
            ["Buy in the last 30 minutes.", "PSX's official close is the volume-weighted price of the last half hour, which is what every result here assumes. Never pay more than the signal's maximum price; if the stock is already above it, skip."],
            ["Sell in the opening auction on the ex-date.", "Enter the sell order in the pre-open session so it executes at the opening price. You still receive the dividend: owning the shares at the close before the ex-date is what entitles you."],
            ["Keep the protective stop.", "It's set at three times the stock's typical daily range below your entry. It rarely triggers, but it caps the occasional collapse."],
            ["Costs and taxes.", "Results deduct 0.6% per round trip (brokerage, levies and a little slippage) and 15% tax on the dividend (filer rate). Non-filers pay 30% on dividends, which cuts the average to about +0.16%, close to break-even: the signal is only really worthwhile for tax filers. The share price usually ends below your purchase price, so the trade mostly creates capital losses rather than taxable gains. Check how your broker nets them."],
          ].map(([t, d]) => (
            <div key={t} className="p-5">
              <h3 className="font-semibold text-ink">{t}</h3>
              <p className="mt-1 text-sm leading-relaxed text-ink-2">{d}</p>
            </div>
          ))}
        </Card>
      </Section>

      <Section id="warnings" title="Warnings" subtitle="Situations where buying has reliably done worse than comparable stocks. Shown on stock and signal pages; they never create trades.">
        <TableWrap>
          <table className="w-full">
            <tbody className="divide-y divide-line">
              {WARNINGS.map(([t, d]) => (
                <tr key={t}>
                  <td className={`${td} w-64 align-top font-medium text-warn`}>{t}</td>
                  <td className="px-4 py-3 text-sm leading-relaxed text-ink-2">{d}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </Section>

      <Section title="What didn't make the cut" subtitle="Every idea had to beat comparable stocks over the same days, profit after costs, work in most years and hold up on 2023–2026 data it was never tuned on.">
        <TableWrap>
          <table className="w-full">
            <tbody className="divide-y divide-line">
              {REJECTED.map(([t, d]) => (
                <tr key={t}>
                  <td className="w-1/2 px-4 py-3 align-top text-sm font-medium text-ink">{t}</td>
                  <td className="px-4 py-3 text-sm leading-relaxed text-ink-2">{d}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </Section>

      <Section title="Honesty rules">
        <ul className="space-y-3 text-sm leading-relaxed text-ink-2">
          <li>
            <b className="text-ink">Published signals never change.</b> Each evening&apos;s signals are written once and kept
            as they were, wins and losses alike. Only the outcome is filled in afterwards, from PSX prices.
          </li>
          <li>
            <b className="text-ink">Backtest and live are labelled separately.</b> Backtest signals are the same engine
            replayed over past data, seeing only what was known each evening. See the <Link href="/history" className="text-brand underline">history</Link>.
          </li>
          <li>
            <b className="text-ink">Limits.</b> Before November 2024 the dividend history comes from an earlier
            database dated to PSX&apos;s own ex-date adjustments; since then, from PSX&apos;s announcements, with the ex-date
            predicted from the book closure exactly as a trader would. Fills at the official close and opening auction
            are assumed achievable for ordinary order sizes.
          </li>
          <li>
            <b className="text-ink">Not investment advice.</b> These are research results describing the past. Trades
            can and do lose money.
          </li>
        </ul>
      </Section>
    </article>
  );
}
