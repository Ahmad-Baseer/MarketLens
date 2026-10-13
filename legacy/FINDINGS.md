# Multi Beggar Finder — Findings

**Data:** AKD research portal, pulled 21 Aug 2026. 641 symbols, ~3,200 requests, zero errors.
**Backtest window:** 2021-08-23 → 2026-05-20 (outcomes need 60 forward days).
**Panel:** 288,377 symbol-days, 501 symbols after liquidity filters.
**Friction charged:** 1.2% round trip on a Rs 30,000 ticket.

---

## Verdict

**The system as specified does not have a demonstrable edge.** One candidate
survives out-of-sample testing, and it is not the kind of system you asked for —
it trades ~28 times a year, holds through 25-30% drawdowns, and its return rests
heavily on a single strong year.

I could not find a rule that reliably identifies stocks about to move +10-20%
over 2-3 months with a tight, clear exit. The specific style you described —
quick target, tight stop, daily fresh candidates — is structurally the losing
configuration in this data.

---

## 1. The exit geometry you'd naturally pick is the worst one

Median ATR20/price on PSX is **4.19%** — a typical stock moves 4.2% in a day.
An 8% stop is under 2 ATR: inside the noise.

Net expectancy per trade, random entry, 2021+:

| stop \ target | +8% | +10% | +12% | +15% | +20% | +30% |
|---|---|---|---|---|---|---|
| **−6%** | −1.16% | −1.07% | −0.99% | −0.84% | −0.61% | −0.10% |
| **−8%** | −1.07% | **−0.95%** | −0.84% | −0.66% | −0.35% | +0.24% |
| −12% | −0.73% | −0.59% | −0.44% | −0.19% | +0.24% | +0.96% |
| −20% | −0.26% | −0.04% | +0.18% | +0.50% | +1.02% | +1.85% |
| −25% | −0.06% | +0.19% | +0.43% | +0.78% | +1.33% | **+2.20%** |

The grid is **monotonic** — wider stop and bigger target always better, right to
the corner. That is not the sweep finding good exits; it is finding "be long in a
bull market." The best cell has **56.5% of trades timing out at day 60**, i.e.
buy-and-hold with a disaster stop. **No exit rule rescues a random entry.**

## 2. Cheap stocks do swing harder — but it does not help you

Your instinct was half right. By price bucket:

| price | P(touch +10%) | mean MFE | mean MAE | P(+10% first) | net exp |
|---|---|---|---|---|---|
| < Rs 5 | **74.9%** | **+41.3%** | **−18.4%** | 42.9% | −1.5% |
| Rs 10-20 | 64.3% | +26.9% | −15.6% | 43.4% | −1.1% |
| Rs 100-300 | 62.2% | +22.1% | −14.0% | 45.6% | −0.7% |
| Rs 300+ | 56.1% | +18.9% | −13.0% | 41.0% | −1.3% |

Sub-Rs-5 stocks reach +10% far more often (74.9% vs 56.1%) and run further
(+41% vs +19%). **But they fall just as much harder** (−18.4% vs −13.0%), so with
any fixed stop the stop gets hit first. P(+10% before −8%) is flat ~43-46% across
every price bucket. The volatility is real; the profit is not.

Also: the "more shares for the same money" idea is arithmetically empty. Returns
are percentages. Rs 100,000 into a Rs 25 stock that gains 20% and Rs 100,000 into
a Rs 900 stock that gains 20% both return Rs 20,000.

## 3. Signals that are actively HARMFUL (high confidence)

Scored against composition-matched controls (same year, price bucket, liquidity
quartile, volatility quartile):

| signal | n | P(win) | control | edge | z | yrs+ |
|---|---|---|---|---|---|---|
| Momentum 60d top quintile | 55,726 | 43.6% | 47.0% | **−3.4%** | −16.0 | 1/6 |
| Quiet chart + volume >3× | 1,139 | 37.9% | 49.1% | **−11.2%** | −7.8 | 1/5 |
| Volume 20d/100d > 2× | 35,729 | 43.0% | 45.1% | −2.0% | −7.7 | 2/6 |
| Volume >3× + >30% off high | 1,317 | 32.6% | 39.6% | −7.1% | −5.5 | 0/5 |
| PSX "Unusual Movement" letter | 549 | 37.5% | 45.5% | **−7.9%** | −3.8 | 1/4 |

These directly contradict the playbook in the earlier Gemini answer:

- *"Dead charts coming to life… that sudden volume spike is your entry signal"* —
  the single **worst** signal tested, −11.2% edge at z=−7.8.
- *"Unusual volume/price movement inquiry… a giant flashing sign that a
  speculative run has begun"* — entering there nets **−1.59%/trade** versus
  **+1.96%** for matched controls. By the time the exchange writes the letter you
  are buying from the people who ran it.

Volume expansion and momentum chasing are negative-edge on PSX in this window.

## 4. The one thing that survived — and its problems

**"More than 50% off the 120-day high"** (deep drawdown mean reversion).
5 slots, Rs 30,000 each (Rs 150,000 deployed):

| period | trades | P(win) | CAGR | max DD |
|---|---|---|---|---|
| In-sample 2021-24 | 92 | 48.9% | +3.2% | −32.7% |
| **Holdout 2025-26** | 45 | 48.9% | **+6.5%** | −22.3% |
| Full 4.7 yrs | 134 | 50.0% | **+11.0%** | −27.8% |
| *Random entry, same sim* | 108 | 48.1% | *+0.2%* | *−35.4%* |

It beats random and it survives the holdout. But be clear about what it is:
~28 trades/year, ~25-30% drawdowns, and the yearly edge **flips sign** — +16.1%
(2021), +2.6% (2022), −2.4% (2023), +5.1% (2024), **−9.7% (2025)**, +10.1% (2026).
The full-period CAGR leans hard on a strong 2026.

**The z=+19 signal failed.** "60d momentum bottom quintile" had the largest and
most significant per-trade edge on the scoreboard (+4.0%, z=+19.0, n=55,726) and
still collapsed in the portfolio: in-sample CAGR +5.9%, **holdout −10.2%**, full
period 0.0%, max DD −39.7%. A large per-trade z did not survive contact with
position limits, clustering and friction. That gap is the whole lesson.

## 5. Statistical honesty

- **19 signals were screened.** At |z|>2 roughly one false positive is expected by
  chance. The honest bar is |z|>3. Every PEAD variant (z = +2.2 to +2.5) is
  **suggestive, not established**.
- **~18 independent 60-day windows** in 4.7 years. Enough to detect a large
  effect, not a subtle one.
- The window contains a historic PSX bull run (KSE-100 ~177,000 at time of
  writing). Random-entry portfolios still netted ~0% CAGR because the ATR exit
  truncates upside at 3 ATR while losers run to the time stop — so the geometry
  itself caps participation in the very trend that makes the period look easy.

## 6. Known gaps

- **KSE-100 index history was not pulled** — no true market benchmark, only a
  cross-sectional median proxy. Should be fixed.
- Price history is capped at 5 years by the AKD endpoint. Fundamentals go back
  ~10 years and are **largely unused so far** (728,161 statement rows,
  297,335 ratio rows). Valuation signals — P/B, P/E, earnings yield versus
  sector — are the main untested avenue.
- `unconsolidatedQuarterEpsYOY` is only populated for 2018-19; year-on-year
  comparisons were rebuilt from the raw EPS series.
- AKD's price series is a **total-return** series (dividends and bonuses adjusted
  out). It was de-adjusted to a price-only series for all decision logic;
  validated to 0.000000 absolute error at the 99th percentile.
- Circuit-breaker reality is not modelled: on a limit-down lock you cannot exit
  at all, so realised losses on the worst trades are understated.

## 7. What I would do next, in order

1. **Pull KSE-100 and sector indices** so results can be measured against
   something real rather than a proxy.
2. **Test the valuation data** — it's the largest unused asset and the least
   crowded angle. Cheap-on-earnings with improving quarterlies is the classic
   emerging-market anomaly and is completely untested here.
3. **Longer horizons.** Everything above is 60 days. If edge exists it may live
   at 120-180 days, where fundamentals actually re-rate.
4. **Stop looking for a daily screener.** The evidence says candidates worth
   taking appear a couple of dozen times a year, not every morning. A system that
   returns 10 names daily would be manufacturing them.

---

*Not investment advice. I am not a licensed financial adviser. Every number here
comes from a 4.7-year sample in an unusually strong market and should be treated
as evidence about the past, not a forecast.*
