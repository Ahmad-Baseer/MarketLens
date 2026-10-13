# MBF — PSX signal provider

Short-horizon (1 day – 1 week) signals for Pakistan Stock Exchange equities,
backed by fundamentals and technicals, with a fully transparent track record.

**Status:** step 1 of 5 — data foundation. Signals, web app and deployment come next.

```
backend/      Python package `mbf`: PSX client, ingest, adjustment, quality checks
  mbf/psx/      client (request key, rate limit, retries) + HTML parsers
  mbf/ingest/   prices, reference data, company fundamentals, events, AKD seed
  tests/        parser and adjustment tests (saved PSX pages as fixtures)
data/         Parquet store (not in git) — see backend/mbf/store.py for layout
reports/      generated reports, e.g. data_quality.md
legacy/       the previous screener, research and AKD CSV pulls (kept for reference)
```

## Setup (once)

Needs Python 3.11+.

```
python -m venv .venv
.venv\Scripts\python -m pip install -e "backend[dev]"
```

## Load the data (once, ~2–3 hours, all automatic)

```
.venv\Scripts\python -m mbf backfill-prices        # daily prices 2000 -> today
.venv\Scripts\python -m mbf seed-akd               # import legacy/akd_data once
.venv\Scripts\python -m mbf ref                    # symbols, sectors, index levels
.venv\Scripts\python -m mbf company-sweep          # fundamentals + report list
.venv\Scripts\python -m mbf events --since 2024-01-01
.venv\Scripts\python -m mbf adjust                 # dividend/bonus/rights adjustment
.venv\Scripts\python -m mbf quality                # -> reports/data_quality.md
```

## Every evening (after 6 pm PKT)

```
.venv\Scripts\python -m mbf update
```

Fetches the new session(s), re-adjusts prices, refreshes index levels,
payouts and announcements, and re-reads fundamentals for any company that just
filed results. Add `--full-sweep` once a week to refresh every company.

## Tests

```
cd backend
..\.venv\Scripts\python -m pytest
```

## How the data works (the non-obvious parts)

- **No login, no CSVs.** Everything comes from the public PSX Data Portal. Its
  data calls need a key that the homepage embeds (`window.__ps._k`); the client
  reads it the same way the site's own JavaScript does and refreshes it on 403.
  Requests are rate-limited (`MBF_REQUEST_INTERVAL`, default 0.8 s).
- **Corporate actions come from PSX's LDCP.** On an ex-date PSX sets the
  previous-close reference to the adjusted value, so `LDCP / previous close` is
  the exact factor for any dividend, bonus or rights issue, and the daily total
  return is simply `close / LDCP - 1`.
- **Point-in-time fundamentals.** Every company sweep is stored by date, and
  each reported figure keeps the date it was first seen, so backtests never use
  numbers before they were public. History before this pipeline started comes
  from the one-time AKD import (2018+).
- **Not everything PSX labels "equity" is a stock.** Futures (`MCB-OCTB`),
  government sukuk and T-bills (`P01GIS…`, `PK03TB…`), TFCs and the odd index
  code are filtered out before anything else runs.
- **Known data limits** (details in `reports/data_quality.md`, section 7):
  research-grade data starts 2013-11-04 — before that PSX has no real opening
  prices and never adjusted LDCP for dividends/bonuses, so older rows are kept
  with `modern = False` for market context only; the Aug–Dec 2008 price floor
  is flagged as untradeable;
  daily moves beyond any circuit breaker are flagged `suspect`; PSX sometimes
  returns an empty table for a trading day, so empty days are retried and can
  be re-checked with `mbf recheck-holidays`.
- **Legacy bugs, fixed here:** the old `refresh.py` treated AKD's `dividend`
  field as % of par and divided by 10 (it is already rupees per share), and
  used AKD's ex-dates, which are usually one session late.

*Not investment advice.*
