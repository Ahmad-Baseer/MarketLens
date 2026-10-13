# Multi Beggar Finder — how to run it

## Quick start (this is the whole thing)

**1. Pull the data.** Open <https://research.akdtrade.biz/screener>, logged in.
Press `F12` → **Console**. Paste all of `AKD_PULL.js`, hit Enter, then type:

```js
MBF.test()      // 3 seconds — confirms everything is reachable. Run this first.
MBF.prices()    // ~4 min   — daily refresh
MBF.full()      // ~25 min  — weekly/monthly, refreshes fundamentals too
```

Chrome may show *"Allow multiple downloads?"* — click **Allow**. Keep the tab
open and in the foreground.

**2. Move the downloaded `mbf_*.csv` files into `D:\Investments\Multi Beggar Finder`.**

**3. Rebuild.**

```
python refresh.py
```

~17 seconds. Writes `screen_today.csv` and `mbf_screen.html`. Open the HTML.

That's it. Two steps, two files.

---

## Why the pull can't be Python

I tested this rather than assuming. The AKD endpoints need your logged-in
session cookie:

| endpoint | without cookie |
|---|---|
| `/api/v3/market?path=/daily/ASTM` | **401** |
| `/announcements/NULL?...` | returns empty |
| `/api/v3/company-statement?...` | **401 even with a valid bearer token** |

So a standalone script would need either your password or your Chrome cookie
store. Running inside the page avoids both — nothing leaves your browser except
the CSV files. The bearer token for the statement endpoints is read live from
the page's `<meta name="access-token">` tag, which rotates, so it can't be
hard-coded anywhere.

## Refresh cadence

| file | how often | why |
|---|---|---|
| `mbf_prices.csv` | daily | price, ATR, drawdown, momentum |
| `mbf_announcements.csv` | daily (it's free — 9 requests) | new results filings; **also every dividend/bonus/rights ex-date** |
| `mbf_fundamentals.csv` | monthly | annual ratios, moves slowly |
| `mbf_statements.csv` | monthly | quarterly statements |
| `mbf_profiles.csv` | quarterly | sector, active/delisted flag |

`MBF.prices()` deliberately pulls the **full 2018-onward** announcement history
even on a daily run. That file is not just news — it carries the ex-dates that
de-adjust AKD's total-return price series back to real prices, and it supplies
the 5-year P/B medians. Overwriting it with a 2-year stub would silently corrupt
both, so it always pulls the lot.

## `refresh.py` options

```
python refresh.py                 rebuild everything (default)
python refresh.py --check         validate the input CSVs and stop
python refresh.py --dir "E:\data" look for the CSVs elsewhere
python refresh.py --top 30        print 30 rows instead of 15
```

It finds the CSVs automatically — next to itself, in a `raw/` subfolder, one
level up, or `D:\Investments\Multi Beggar Finder`.

Needs `pandas` and `numpy`. `pyarrow` is optional: with it, `refresh.py` also
writes `work/*.parquet`, which the research scripts below need. Without it the
screen works exactly the same.

```
pip install pandas numpy pyarrow
```

**It self-checks on every run.** Look for this line:

```
de-adjust check on 393 dividend events: 99th-pct error 4.85e-05  ->  OK
```

That is verifying the dividend/bonus de-adjustment still reproduces the
mechanical ex-date drop. If it ever says FAILED, the price-only returns are
wrong and nothing downstream should be trusted — tell me and I'll look.

---

## The research scripts

These are **not needed for the screen**. They exist to re-test whether the
signals actually work, which is worth redoing once you have meaningfully more
history (AKD caps price data at 5 years, so the window widens as time passes).

Run them in this order, from the same folder, after `refresh.py` has produced
`work/*.parquet`:

### `panel.py` — build the test panel *(~9s)*

Turns the price history into one row per (symbol, day) with forward 60-day
outcomes attached: did it hit +3×ATR before −2.5×ATR, how far did it run for and
against you, what did it close at on day 60. Everything downstream reads this.

Writes `work/panel.parquet`. Prints the random-entry benchmark — currently
P(win) 0.458, net +0.03% on the ATR geometry. **That is the number every signal
has to beat.**

### `baserate.py` — what a coin flip looks like *(~9s)*

The honest baseline, split by year and by price bucket. This is where you can
see that sub-Rs-5 stocks touch +10% far more often (74.9%) and run further
(MFE +41%) but also fall harder (MAE −18%), so P(+10% before −8%) ends up flat
at 43-46% across *every* price bucket.

Writes `out/base_rate_by_year.csv`, `out/base_rate_by_price.csv`.

### `sweep.py` — exit geometry *(~16s)*

Grid of stop × target, fixed and ATR-scaled. Read it for the shape, not the
winner: the grid is monotonic toward wider stops and bigger targets, which means
it's measuring the bull market rather than exit skill. The useful fact is that
the intuitive −8%/+10% rule is the *worst* corner at −0.95% per trade.

Writes `out/geometry_fixed.csv`, `out/geometry_atr.csv`.

### `signals.py` — the scoreboard *(~6s)*

Tests 19 signals against a composition-matched control (same year, price bucket,
liquidity quartile, volatility quartile). This is the file that found the
negative-edge results the screen now shows as caution flags.

Writes `out/signal_scoreboard.csv`. Read the `z` and `yrs+` columns, not `edge`:

- `|z| > 3` is the honest bar — 19 signals were screened, so at `|z| > 2` you
  expect about one false positive by chance.
- `yrs+` of `4/6` means it worked in 4 of 6 years. Anything at `2/6` is noise
  however good the pooled number looks.

### `validate.py` — does it survive contact with reality *(~6s)*

Per-year breakdown plus a portfolio simulation: Rs 30,000 per position, a hard
cap on concurrent holdings, one position per symbol, real friction, and a proper
holdout (rules fixed on 2021-24, run untouched on 2025-26). Also runs the same
simulation on random entries as the benchmark.

This is the file that killed the best-looking signal. "60-day momentum bottom
quintile" had edge +4.0% at **z = +19.0** on 55,726 observations — and still went
in-sample +5.9% CAGR, **holdout −10.2%**, full period 0.0%. A large per-trade z
did not survive position limits, signal clustering and costs. If you only read
one of these files, read this one.

Writes `out/portfolio_results.csv`, `out/portfolio_random.csv`.

### `eventstudy.py` — helper module

Imported by the others, not run directly.

---

## Reading the screen

- **Score is a ranking, not a probability.** It means "worth twenty minutes of
  reading", not "this will go up".
- **Sort by other columns.** The weighting is my opinion; the columns are facts.
  Sorting by "off 12m hi" or P/B surfaces different situations entirely.
- **Watch `data coverage`.** A score of 74 at 72% coverage is a weaker claim than
  71 at 100%, because missing inputs score neutral.
- **Greyed rows need a corporate-action check first.** Their per-share ratios are
  computed against a share count that has since changed.
- **Cautions cite measured numbers.** A flagged name isn't disqualified — it
  needs a better reason than the screen can give you.

## Three things to check by hand before any entry

1. **Read the actual filing on the PSX site.** The EPS here comes from a summary
   feed that cannot tell operating profit from a one-off gain.
2. **Confirm the share count.** Any bonus, rights or split since the last
   reported accounts makes every per-share ratio stale. The VERIFY flag catches
   what's in this data — it can't catch what isn't.
3. **Check spread and depth on your terminal.** A name showing Rs 2m/day
   turnover can still have a 2% spread, and on a Rs 30,000 ticket that's a real
   bite out of a 10% target.

## Troubleshooting

| symptom | cause |
|---|---|
| `MBF is not defined` | the paste didn't complete — re-paste the whole file |
| `401 — session expired` mid-run | reload the AKD page, log in, re-paste, re-run |
| `access-token meta tag missing` | you're not logged in on that page |
| only some files downloaded | Chrome blocked multiple downloads — click Allow and re-run |
| `Missing required file(s)` | the CSVs aren't in the folder `refresh.py` is looking at; use `--dir` |
| `de-adjust check ... FAILED` | stop and tell me; price-only returns are unreliable |
| screen looks stale | check the `as of` date in the HTML header against today |

---

*Not investment advice. I'm not a licensed financial adviser. Every backtest
number referenced here comes from a 4.7-year sample in an unusually strong
market and is evidence about the past, not a forecast.*
