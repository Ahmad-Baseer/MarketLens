# Step 2 research — what actually works at 1 day to 1 week on PSX

*Data: PSX Data Portal, research-grade era 2013-11-04 → 2026-10-13 (3,205 sessions).
Company events (results, dividends, board meetings) from the AKD history, 2018 → 2026.
Universe: up to 200 most-traded stocks per day (≥ Rs 2m/day, price ≥ Rs 5). Costs 0.6% per
round trip; dividends collected are net of 15% withholding. Every signal is compared with a
**same-day matched control** — random universe stocks in the same liquidity and volatility
bucket, traded with the same rule — and significance is measured across dates.
Development ≤ 2022, holdout 2023+. Full tables: `reports/research_signals.md`.*

## Bottom line

1. **One signal family survives every test: the dividend run-up.** Buy near the close
   5 sessions before the ex-date of an announced cash dividend yielding 2–7%, sell at the
   ex-date's opening auction (dividend collected). **+0.72% per trade after costs and tax,
   60% winners, +1.19% better than same-day controls, t = 7.7, better than control in
   9 of 9 years, holdout edge +1.15%.**
2. **When you trade matters as much as what.** PSX's liquid stocks gain **+0.28% overnight**
   and lose **−0.20% during the session** on average, every year 2014–2026. Buying at the
   open systematically overpays; buying near the close (PSX's close = VWAP of the last 30
   minutes) and selling at the opening auction is worth ~0.5% per trade.
3. **Generic technical and fundamental signals don't clear costs at this horizon.**
   Short-term reversal, pullbacks in uptrends, breakouts, deep-value rebounds, pre-results
   run-ups and a combined 23-factor model all show small real edges (+0.1% to +0.4%) that
   leave the trade at roughly break-even after 0.6% costs.
4. **Several things reliably *hurt*** — they become warnings in the product, not signals:
   holding after an ex-date, buying after an earnings beat, buying a stock that closed at
   its low on a big down day, volume spikes, and PSX unusual-movement letters.
5. **Frequency is the product constraint:** ~68 qualifying signals a year, concentrated in
   results seasons (Mar–Apr, Sep–Oct). About 47 sessions a year have at least one signal;
   most days have none. Because dividend dates are announced in advance, upcoming signals
   can be shown days ahead.

## 1. The baseline every signal must beat

A random universe stock, bought at the next open:

| hold | win after costs | mean gross | mean net |
|---|---|---|---|
| 1 day (sell at close) | 30% | −0.20% | −0.80% |
| 3 days | 38% | −0.05% | −0.65% |
| 5 days | 40% | +0.10% | −0.50% |

## 2. The overnight effect

| | 2014 | 2016 | 2018 | 2020 | 2022 | 2024 | 2025 | 2026 | all |
|---|---|---|---|---|---|---|---|---|---|
| close → next open | +0.29% | +0.23% | +0.15% | +0.20% | +0.16% | +0.48% | +0.50% | +0.31% | **+0.28%** |
| open → close | −0.10% | −0.06% | −0.17% | −0.06% | −0.26% | −0.21% | −0.36% | −0.36% | **−0.20%** |

Same random stock, 5-day hold, after costs: buy next open / sell at close **−0.50%**;
buy near next close / sell at an opening auction **−0.02%**.

The opening price is a real auction print (09:30:00, with volume); the close is the VWAP of the
last 30 minutes. Both are achievable for normal order sizes. Intraday ticks for the 150
most-traded stocks are now saved every evening to measure how much size each absorbs.

## 3. The dividend run-up

**Rule (fixed before the holdout was examined in this form):**
- a cash dividend has been announced (the announcement must precede the entry), no bonus attached;
- yield = dividend ÷ price at signal day, between **2% and 7%**;
- buy near the close **5 sessions before the ex-date**; sell at the **ex-date's opening auction**;
- protective stop 3 × ATR below entry (costs ~0.08%/trade; caps the tail);
- ex-date = book-closure start − 1 session (T+1 settlement from 2026-02-09; T+2 before).
  This rule matched 90–97% of 2,900 historical payouts exactly.

| year | signals | win | mean net | edge vs control |
|---|---|---|---|---|
| 2018 | 52 | 46% | −0.33% | +1.21% |
| 2019 | 59 | 56% | +0.44% | +1.25% |
| 2020 | 47 | 66% | −0.29% | +0.98% |
| 2021 | 79 | 52% | −0.23% | +1.42% |
| 2022 | 53 | 62% | +1.18% | +1.27% |
| 2023 | 54 | 67% | +1.62% | +0.55% |
| 2024 | 100 | 71% | +2.06% | +1.37% |
| 2025 | 94 | 64% | +0.71% | +0.85% |
| 2026 | 76 | 55% | +0.72% | +1.62% |

The edge over the control is positive every year; the absolute result follows the market
(negative in the 2018/2020/2021 drawdowns). Median trade +0.75%; worst −25% (without stop).

**Robustness** (holding from announcement to ex-date, ~14 sessions, yield ≥ 2%):
+1.64% net; still +1.24% at 1.0% costs, +0.88% for non-filers (30% dividend tax),
+1.62% when entering two sessions late.

**What doesn't matter / what does:**
- yield 2–3% +0.57%, 3–4.5% +0.73%, 4.5–7% +0.94% net; **> 7% fails in the final week**
  (special/one-off payouts — the market prices them early);
- payout covered by earnings or not: no difference (coverage is still shown as risk context);
- liquidity: works in all buckets, strongest outside the top 50.

**Why it can be live:** payouts are announced a median 13 sessions before the ex-date
(91% leave ≥ 6 sessions). The PSX payout feed gives the dividend as % of par; par is
derived from past ex-date drops in PSX's own data (Rs 10 for most; some Rs 5/2/1/100).

## 4. What doesn't work (best rule per family, 5-day)

| family | mean net | edge vs control | t | verdict |
|---|---|---|---|---|
| short-term reversal (worst 5-day decile) | +0.14% | +0.23% | +5.6 | real but too small |
| reversal + profitable & growing EPS | +0.09% | +0.25% | +3.8 | real but too small |
| pullback in uptrend (RSI2 < 10) + fundamentals | +0.21% | +0.37% | +2.8 | weak |
| pre-results run-up (last result beat) | −0.23% | +0.41% | +3.6 | doesn't clear costs |
| breakout after contraction | −0.10% | +0.30% | +2.3 | weak, inconsistent |
| 23-factor walk-forward model, top 3/day | +0.06% | +0.19% | +2.3 | no better than parts |
| buying after an earnings beat | −0.6% to −0.8% | −0.4% to −0.7% | −3.4 | **avoid** |
| buying after the ex-date (3–5 nights) | −0.6% to −0.7% | −0.6% to −0.7% | −6.2 | **avoid** (0–1 of 9 years positive) |
| buying a weak close (bottom 15% of range, −3% day), sell next open | −1.04% | −0.44% | −23.8 | **avoid** |
| volume spike > 3× | — | −0.17% to −0.25% | −8.8 | **avoid** |
| PSX unusual-movement letter | — | −0.2% to −0.6% | −1.8 | avoid (weak) |

Also tested and rejected for v1: bonus-share run-up (strong on paper, n ≈ 12/yr, and only
by holding into the ex-date — the bonus shares arrive weeks later at an unknown price).

## 5. Following every signal

Capital split into 3 slots (a signal takes a free slot; idle cash earns 0 in this test):

| | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| signals | −2.0% | +8.0% | −3.8% | +3.3% | +17.3% | +21.5% | +26.6% | +17.3% | +10.1% |
| market (cap-wtd, incl. dividends) | −12.5% | +3.7% | +10.0% | −1.3% | −11.8% | +44.8% | +82.5% | +49.1% | −5.4% |

Average +10.9%/yr with capital idle most of the time. It held up in the 2022 bear market and
trails buy-and-hold badly in strong bull years. This is a short-term trading service, not a
substitute for long-term investing — the product should say so.

## 6. Caveats

- Executions are assumed at PSX's official close (VWAP of the last 30 min) and opening
  auction. Captured intraday ticks will confirm this over the coming weeks.
- 2018–2026 event data comes from AKD; ~6% of AKD payouts couldn't be matched to a PSX
  ex-date and are excluded.
- The holdout (2023–2026) includes an exceptional bull market; the edge over controls,
  not the absolute return, is the robust quantity.
- 34 families × up to 9 rules were tested; the dividend run-up clears the multiple-testing
  bar (t > 3) by a wide margin in development and holdout separately.

*Not investment advice. Results describe the past.*
