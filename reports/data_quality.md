# Data-quality report — 2026-10-13

Source: PSX Data Portal (dps.psx.com.pk). Independent check: legacy AKD pulls.

## 1. Coverage

- Range: **2000-01-03 -> 2026-10-13**, 6,610 trading days, 377 weekday holidays/closures detected
- Research-grade (modern) era: **2013-11-04 -> 2026-10-13**, 3,205 trading days — see section 7
- Weekdays with no file (fetch failed, needs a retry): **0**
- Calendar check vs PSX's KSE-100 series: since 2021-10-13: 1240 KSE-100 sessions vs 1240 of ours; 0 index days missing from our data, 0 extra days in ours
- Equity rows: 2,484,957 raw, 2,468,778 after cleaning; 1,705 distinct equity symbols ever listed

Per year (equities only: futures, bonds, T-bills, sukuks and index codes excluded):

| year | trading_days | median_listed | median_traded |
|---|---|---|---|
| 2000 | 242 | 250 | 248 |
| 2001 | 234 | 208 | 202 |
| 2002 | 249 | 295 | 263 |
| 2003 | 247 | 372 | 340 |
| 2004 | 249 | 398 | 371 |
| 2005 | 250 | 356 | 330 |
| 2006 | 241 | 360 | 338 |
| 2007 | 244 | 380 | 359 |
| 2008 | 248 | 322 | 322 |
| 2009 | 246 | 375 | 340 |
| 2010 | 250 | 416 | 397 |
| 2011 | 248 | 366 | 362 |
| 2012 | 249 | 367 | 363 |
| 2013 | 247 | 359 | 354 |
| 2014 | 246 | 392 | 384 |
| 2015 | 249 | 387 | 369 |
| 2016 | 248 | 654 | 364 |
| 2017 | 249 | 383 | 376 |
| 2018 | 246 | 357 | 350 |
| 2019 | 247 | 326 | 318 |
| 2020 | 251 | 365 | 356 |
| 2021 | 247 | 386 | 382 |
| 2022 | 248 | 355 | 350 |
| 2023 | 246 | 343 | 338 |
| 2024 | 246 | 444 | 442 |
| 2025 | 250 | 477 | 477 |
| 2026 | 193 | 490 | 490 |


## 2. Daily returns vs AKD

Daily total returns compared on 572,563 symbol-days where both sources have the same previous session (2012-02-17 -> 2026-08-27).
- Agree within 0.1%: **99.9%**; within 0.5%: **99.9%**

| year | symbol_days | within_0_1pct | within_0_5pct |
|---|---|---|---|
| 2012 | 1163 | 1.000 | 1.000 |
| 2013 | 3222 | 1.000 | 1.000 |
| 2014 | 4375 | 0.998 | 0.998 |
| 2015 | 7924 | 0.996 | 0.996 |
| 2016 | 18121 | 1.000 | 1.000 |
| 2017 | 10090 | 0.998 | 0.998 |
| 2018 | 7464 | 0.999 | 0.999 |
| 2019 | 7417 | 0.999 | 0.999 |
| 2020 | 9714 | 0.998 | 0.999 |
| 2021 | 39754 | 1.000 | 1.000 |
| 2022 | 86557 | 1.000 | 1.000 |
| 2023 | 83891 | 1.000 | 1.000 |
| 2024 | 101770 | 0.999 | 1.000 |
| 2025 | 115105 | 0.999 | 0.999 |
| 2026 | 75996 | 0.997 | 0.997 |

Largest disagreements (either source may be the wrong one):

| symbol | date | close | ret | akd_ret | diff |
|---|---|---|---|---|---|
| ITANZ | 2026-02-09 | 3.6300 | 0.3058 | 59.5000 | 59.1942 |
| ICIBL | 2026-07-13 | 24.2400 | -0.0999 | 4.9558 | 5.0557 |
| SJTM | 2020-03-19 | 25.0000 | 0.0000 | 1.3386 | 1.3386 |
| SUHJ | 2024-08-30 | 52.7100 | 0.1000 | 1.3743 | 1.2744 |
| WAVESAPP | 2022-07-15 | 15.2000 | -0.0749 | 1.0822 | 1.1571 |
| SMTM | 2022-07-15 | 15.2000 | -0.0749 | 1.0822 | 1.1571 |
| LSEVL | 2025-08-29 | 15.0000 | 0.0115 | 1.0229 | 1.0115 |
| ITANZ | 2026-02-17 | 9.4900 | 0.1178 | 1.0857 | 0.9679 |
| GLAT | 2018-01-25 | 65.0000 | 0.0000 | 0.9502 | 0.9502 |
| ISHT | 2019-05-23 | 18.0000 | 0.0000 | 0.8967 | 0.8967 |
| DLL | 2026-06-08 | 60.4300 | -0.0328 | -0.9033 | 0.8705 |
| SRVI | 2026-08-24 | 215.1900 | -0.0433 | -0.9043 | 0.8610 |


## 3. Corporate actions vs AKD

AKD payout events since 2018 with PSX prices on both sides: **3,075**. Found as an LDCP adjustment within ±5 sessions: **93.9%**.
- Cash dividends: PSX-implied amount matches AKD's within 2%: **99.3%** of 2,546
- PSX detected 3,379 adjustments since 2018 in total (AKD's file also misses some, e.g. rights and splits).

| kind | AKD events | found in PSX LDCP |
|---|---|---|
| cash dividend | 2686 | 94.8% |
| bonus | 290 | 90.7% |
| rights | 101 | 76.2% |

Where PSX puts the event relative to AKD's ex-date:

| PSX date minus AKD ex-date (sessions) | events |
|---|---|
| -5 | 5 |
| -4 | 6 |
| -3 | 8 |
| -2 | 367 |
| -1 | 2059 |
| 0 | 310 |
| 1 | 47 |
| 2 | 25 |
| 3 | 28 |
| 4 | 17 |
| 5 | 14 |

Most recent AKD events with no PSX adjustment nearby:

| symbol | ex_date | div_rs | bonus_r | right_r |
|---|---|---|---|---|
| NICL | 2026-09-12 | 2.000 | 0.000 | 0.000 |
| WAVESAPP | 2026-08-25 | 0.000 | 0.000 | 0.560 |
| FPRM | 2026-07-17 | 0.000 | 0.000 | 0.500 |
| GCWL | 2026-06-10 | 0.000 | 0.000 | 0.005 |
| MRNS | 2026-06-03 | 0.500 | 0.000 | 0.000 |
| EWIC | 2026-04-25 | 0.000 | 0.100 | 0.000 |
| UNIC | 2026-04-17 | 0.000 | 0.200 | 0.000 |
| MFFL | 2026-03-16 | 0.000 | 0.000 | 0.121 |
| WASL | 2026-03-02 | 0.000 | 0.000 | 0.242 |
| FCL | 2025-10-06 | 0.500 | 0.025 | 0.000 |
| GIL | 2025-10-03 | 3.000 | 0.000 | 0.000 |
| CSIL | 2025-04-22 | 0.000 | 0.000 | 0.380 |


## 4. Suspicious moves

Rows flagged `suspect` (daily move beyond any circuit breaker PSX has used: > max(30%, Rs 1.5)): **913** of 2,325,718 traded rows (0.039%). Mostly thinly traded small stocks in 2000-2005; research excludes them. Modern era only: **13** of 1,219,477 traded rows (0.0011%).

| year | suspect rows |
|---|---|
| 2000 | 393 |
| 2001 | 203 |
| 2002 | 35 |
| 2003 | 74 |
| 2004 | 67 |
| 2005 | 38 |
| 2006 | 18 |
| 2007 | 27 |
| 2008 | 18 |
| 2009 | 3 |
| 2010 | 5 |
| 2011 | 9 |
| 2012 | 4 |
| 2013 | 6 |
| 2014 | 1 |
| 2015 | 1 |
| 2016 | 5 |
| 2020 | 1 |
| 2023 | 1 |
| 2024 | 2 |
| 2026 | 2 |

Largest:

| symbol | date | ldcp | close | volume | ret |
|---|---|---|---|---|---|
| KOHP | 2000-06-07 | 0.0500 | 5.0500 | 14,500.0000 | 100.0000 |
| DGKPS | 2003-04-21 | 0.0000 | 10.0000 | 500.0000 | 49.0000 |
| MUREB | 2016-09-15 | 77.4300 | 1,200.1800 | 53,150.0000 | 14.5002 |
| SGMLPS | 2005-01-11 | 0.0000 | 11.0000 | 2,000.0000 | 13.6667 |
| JSCLR | 2003-08-29 | 0.0000 | 22.0000 | 500.0000 | 13.1935 |
| ICPXIIIR | 2003-12-05 | 0.0000 | 7.0000 | 1,000.0000 | 13.0000 |
| STML | 2003-11-05 | 2.0500 | 23.7000 | 1,000.0000 | 10.5610 |
| YOUTM | 2001-09-06 | 0.0000 | 93.0000 | 500.0000 | 9.2198 |
| ICPVIR | 2003-12-05 | 0.0000 | 2.5000 | 1,500.0000 | 9.0000 |
| BIPLR | 2007-01-10 | 0.0000 | 3.0000 | 6,500.0000 | 5.6667 |
| BURMA | 2000-03-15 | 0.0000 | 11.0000 | 1,500.0000 | 4.5000 |
| BAPLR | 2007-10-02 | 0.0000 | 2.5000 | 500.0000 | 4.0000 |

LDCP gaps not applied as corporate actions: 144 ({'after_gap': 137, 'implausible': 7})


## 5. Market proxy vs KSE-100

Two proxies, 2000-01-04 -> 2026-10-13: **CW** = top-100 by estimated free-float market cap, cap-weighted (KSE-100's own method); **EW** = 100 most-traded stocks, equal-weighted (the 'average liquid stock'). Compared with PSX's KSE-100 on 1,239 common days:
- Daily correlation: CW **0.996** (beta 1.02), EW **0.925** (beta 1.20)
- Cumulative over the overlap: KSE-100 +281.2% (price only); CW +236.2%, EW +123.1% (both include dividends)

CW coverage by year — share of traded value in names with a known share count (falls in early years as since-delisted companies drop out):

| year | cw_coverage | cw_names |
|---|---|---|
| 2000 | 0.98 | 100.00 |
| 2001 | 0.98 | 100.00 |
| 2002 | 0.99 | 100.00 |
| 2003 | 0.98 | 100.00 |
| 2004 | 0.97 | 100.00 |
| 2005 | 0.99 | 100.00 |
| 2006 | 0.98 | 100.00 |
| 2007 | 0.98 | 100.00 |
| 2008 | 0.99 | 100.00 |
| 2009 | 0.99 | 100.00 |
| 2010 | 0.99 | 100.00 |
| 2011 | 1.00 | 100.00 |
| 2012 | 0.99 | 100.00 |
| 2013 | 0.98 | 100.00 |
| 2014 | 0.97 | 100.00 |
| 2015 | 0.98 | 100.00 |
| 2016 | 0.99 | 100.00 |
| 2017 | 1.00 | 100.00 |
| 2018 | 1.00 | 100.00 |
| 2019 | 1.00 | 100.00 |
| 2020 | 1.00 | 100.00 |
| 2021 | 1.00 | 100.00 |
| 2022 | 0.99 | 100.00 |
| 2023 | 1.00 | 100.00 |
| 2024 | 1.00 | 100.00 |
| 2025 | 1.00 | 100.00 |
| 2026 | 1.00 | 100.00 |



## 6. Other tables

- Symbols: 1,041 listed, 757 equities, 38 sectors
- Indices: ALLSHR 2021-10-13->2026-10-13 (1240); KMI30 2021-10-13->2026-10-13 (1240); KMIALLSHR 2021-10-13->2026-10-13 (1240); KSE100 2021-10-13->2026-10-13 (1240); KSE30 2021-10-13->2026-10-13 (1240); PSXDIV20 2022-09-05->2026-10-13 (1019)
- Fundamentals snapshot 2026-10-13: 757 companies; P/E (TTM) present 50.1%, market cap 100.0%, annual EPS 80.1%, quarterly EPS 73.3%, sales 60.9% (banks report mark-up instead)
- Report PDFs listed: 21,278 across 624 companies (15,207 quarterly, 6,071 annual)
- Payouts: 724 components, 2024-11-04 -> 2026-10-06; unparsed kind: 0.0%
- Announcements: 50,328, 2024-01-01 -> 2026-10-13
- AKD seed announcements: 120,972 rows
- AKD seed fundamentals: 297,316 rows
- AKD seed statements: 1,004,814 rows
- AKD seed prices_total_return: 573,432 rows


## 7. Known data limits

- **Research-grade data starts 2013-11-04 (`config.MODERN_FROM`).** Before it PSX's "open" is a
  copy of the previous close on ~90% of rows, and LDCP is never adjusted for dividends,
  bonuses or rights (zero adjustments 2012Q1-2013Q3; 35 in 2013Q4, ~80 per quarter after).
  Older rows are kept with `modern = False`: opens are unknown, returns are price-only, and
  every ex-date shows as a fake drop. Use them for long-run market context only — never to
  backtest a 1-5 day signal.
- **About 20 symbols in 2016** have a blank LDCP for most of the year (exchange-merger period);
  their returns fall back to the previous close, so their 2016 ex-dates are unadjusted.
- **Aug 27 - Dec 15, 2008: market floor.** Almost nothing traded and positions could not be
  exited (`config.MARKET_FREEZE`). Backtests must treat it as untradeable, not as flat.
- **PSX occasionally answers a trading day with an empty table.** Empty days are retried
  before being marked as holidays, recent holidays are re-checked on every update, and the
  KSE-100 calendar check above catches any that slip through.
- **Missed corporate actions are rare:** of ~3,000 AKD payout events since 2018, about 18 show
  a price drop that PSX's LDCP did not adjust for (~1 in 100,000 daily returns).
- **AKD's ex-dates are usually one session late** relative to PSX (see section 3); PSX's LDCP
  is the reference, AKD is only a cross-check.
- **No official index before 2021-10** from PSX; the cap-weighted proxy (section 5) stands in.
