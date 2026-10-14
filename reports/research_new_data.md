# New data sources — do they add a 1-day-to-1-week signal?

*Same method and bar as `research_step2.md`. Each trade is compared with same-window
universe stocks in the same liquidity bucket. t-statistics are taken across event dates,
with development ≤ 2022 and holdout 2023+. Costs are 0.6% per round trip; dividends are net of 15% tax.
A new **signal** needs |t| > 3, a profit after costs, most years positive, and it must hold up in the
holdout. A new **warning** needs a consistently negative edge, including in the holdout.*

## Bottom line

| idea | data collected | result |
|---|---|---|
| Rights issues | 167 ex-rights dates 2013–2026 (PSX notices + AKD); 77 with the board-decision date | **No signal.** Effects exist only in illiquid small caps, or are an artifact of how PSX adjusts prices for rights. |
| Index changes (KSE-100, KSE-30, KMI-30) | 73 PSX notices 2013–2026, 628 incoming/outgoing changes | **No signal.** KMI-30 additions are promising but not proven. **Removal from KSE-30 becomes a warning.** |
| NCCPL foreign/local flows | 566 weeks 2015–2026, 11 client types × sectors (collected in the user's browser) | **No signal.** Flows follow the market rather than lead it; sector-level only; and they can't be fetched automatically anyway. |

**Also re-checked: the 3-week "early dividend entry".** Replayed day by day by the live engine at a
2–7% yield, it made only +0.27% per trade with the protective stop (+0.51% without). Its edge over
controls was t 1.8 in 2018–2022. It falls short of the bar, so only the 5-session run-up is published.

## 1. Rights issues

**Events.** Ex-rights sessions come from PSX's own price adjustment, matched to three sources:
- PSX "Issuance of Right Shares" notices (2013–2016);
- PSX "Commencement of trading in unpaid rights" notices (2013–2026);
- AKD's rights records (2018+), which also give the board-decision date.

PSX's notices are published around the ex-date, not at the decision, so before 2018 only
the ex-date is known. Of 77 AKD events, 62 are confirmed by a PSX notice on the same ex-date.

| trade | n | mean net | edge vs control | t | years + | holdout edge (t) |
|---|---|---|---|---|---|---|
| buy 5 sessions before ex, sell at last cum-rights close | 144 | +1.38% | +1.91% | 2.6 | 9/14 | +1.49% (1.1) |
| same, 10 sessions | 140 | +4.67% | +4.41% | 3.6 | 12/14 | +2.85% (1.4) |
| ↳ tradeable stocks only (top-200 universe) | 87 | +1.57% | +2.06% | 1.4 | 9/14 | −3.74% (−1.2) |
| buy after the decision, hold 5 nights | 70 | +1.75% | +1.97% | 1.7 | 5/9 | +2.86% (1.2) |
| ↳ tradeable stocks only | 40 | +1.50% | +1.54% | 1.2 | 4/9 | +1.36% (0.5) |
| buy at the ex-rights close, hold 5 nights | 141 | +0.77% | +0.70% | 0.9 | 7/13 | −1.36% (−0.4) |

- The 10-session run-up into ex-rights is real on paper, but it comes from illiquid small caps.
  Among stocks you could actually trade, it is not significant, and it is negative in the holdout.
- Holding through the ex-date *looks* strong (+1.7% overnight, t 4.7), but this is an artifact.
  PSX marks the share down to the theoretical ex-rights price, which assumes the rights entitlement
  is worth its full theoretical value. In practice letters of rights trade at a discount and start
  trading days later, so the gain can't be realised.
- About 13 rights issues a year (fewer than 8 in tradeable stocks) would be too rare to matter anyway.

## 2. Index recompositions

**Events.** PSX notices for 73 reviews (2013–2026), covering semi-annual reviews, special
recompositions after mergers, and revised notices. The 21 scanned notices were read with open-source OCR.
All 628 changes were matched to tickers.

| trade (buy near the close the day after the notice, sell at the open 5 sessions later) | n | mean net | edge | t | years + | holdout edge (t) |
|---|---|---|---|---|---|---|
| KSE-100 additions | 78 | +0.92% | +0.56% | 0.8 | 6/12 | +1.06% (0.5) |
| KSE-100 deletions | 73 | +1.09% | +0.63% | 0.8 | 5/12 | +0.05% (−0.4) |
| KSE-30 additions | 82 | +0.48% | +0.40% | 1.0 | 8/11 | −0.15% (0.2) |
| **KSE-30 deletions** | 81 | **−1.50%** | **−1.31%** | −2.3 | **1/11** | **−1.22% (−3.2)** |
| **KMI-30 additions** | 131 | **+2.10%** | **+1.39%** | **3.3** | **12/13** | +0.90% (1.0) |
| KMI-30 deletions | 131 | +0.43% | −0.56% | −1.1 | 4/13 | −1.88% (−3.6) |

Holding from the effective date onwards shows nothing for any index (|t| ≤ 1.2).

**KMI-30 additions look promising but are not proven.** Islamic funds benchmark to KMI-30, so
there is a plausible buyer.

Against:
- there are only 26 independent review dates;
- the edge is positive at 18 of them;
- among top-200 stocks it is t 2.6;
- entering one or two days late cuts it to t 2.6 and t 2.2;
- the holdout edge is +0.9% at t 1.0;
- one review (Dec 2021, 3 stocks, +9.8%) contributes a lot.

It is shown as **context** on a stock's page ("joins KMI-30 on <date>"), not as a signal. It
will be re-tested as new reviews arrive, twice a year.

**Removal from KSE-30 becomes a warning.** These stocks lag their controls in 10 of 11 years,
including the holdout.

## 3. NCCPL foreign and local investor flows

**Data.** NCCPL publishes daily net buying by client type and sector:
- foreign: individuals, corporates, overseas Pakistanis;
- local: individuals, companies, banks, NBFCs, mutual funds, insurance, brokers' proprietary books, other.

The site blocks scripts behind a Cloudflare check, so the history was collected in the user's own
browser:
- daily, 9 Dec 2015 – 28 Dec 2016;
- weekly (Monday–Friday ranges, which NCCPL sums exactly) to 12 Oct 2026.

That is 566 weeks in total, ready market only. The data is internally consistent: foreign net plus
local net is zero in every sector-week (median −8e-11 of turnover). The yearly totals also match
the known story, for example foreigners net sold Rs 103.5 bn in 2025.

**Granularity.** NCCPL reports flows by **sector**, not by stock. Nine sectors are reported
throughout: cement, fertilizer, food, E&P, OMCs, power, banks, technology and textile composite.
The rest is pooled as "all other". So a flow signal can only pick sectors.

**Test.** Each week, rank the sectors by a client group's net buying as a share of the sector's
turnover. Buy the top-200 stocks of the chosen sectors near Monday's close, which allows for
publication lag, and sell at the opening auction 5 sessions later. As always, compare with
same-window controls.

| sector rule (next week) | n | mean net | edge | t | years + | holdout edge (t) |
|---|---|---|---|---|---|---|
| foreigners' top-2 sectors | 8,557 | +0.18% | +0.07% | 0.7 | 8/12 | +0.27% (2.2) |
| foreigners' bottom-2 sectors | 8,967 | +0.30% | +0.12% | 1.6 | 8/12 | +0.25% (2.1) |
| foreigners unusually buying a sector (z > 2) | 1,363 | −0.58% | −0.45% | −2.1 | 3/11 | −0.62% (−1.2) |
| mutual funds' top-2 sectors | 8,447 | +0.26% | +0.16% | 1.7 | 6/12 | +0.27% (2.0) |
| individuals' top-2 sectors | 8,039 | +0.17% | +0.07% | 1.0 | 7/12 | +0.08% (0.7) |
| insurers' / companies' / brokers' top sector | ~4,300 each | +0.22–0.25% | +0.14–0.15% | 0.8–1.3 | 7–8/12 | t 1.1–2.0 |
| foreigners' 4-week cumulative, top-2 sectors | 8,910 | +0.25% | +0.08% | 1.2 | 6/11 | +0.13% (0.8) |

Variants also tried: top-1 sectors, unusual selling, and every client group. **Nothing reaches t 3,**
and nothing is significant in both periods. Every rule wins fewer than half of its trades after costs.

**Market timing.** Last week's total foreign flow has a correlation of +0.02 (t 0.4) with the
market's next week. In the *same* week the correlation is +0.10 (t 2.3): foreigners buy when the
market is already rising. Flows follow prices here; they don't lead them.

**Verdict: no signal and no warning.** There's also a practical bar it would have failed: the data
can only be fetched by a person in a browser (Cloudflare), so a public product couldn't update it
every evening without a data agreement with NCCPL. Weekly foreign/local flows could still be shown
as market *context*, sourced manually or by agreement, but they won't drive signals.

*Not investment advice. Results describe the past.*
