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

## Setup (development machine)

Needs Python 3.11+.

```
python -m venv .venv
.venv\Scripts\python -m pip install -e "backend[dev]"
```

## Running it — nothing is manual

**Production (server):** one long-running process does everything.

```
.venv\Scripts\python -m mbf scheduler
```

- On first start with an empty `data/` it **bootstraps** the whole store
  (~2–3 hours: 26 years of prices, fundamentals, announcements). Interrupted?
  Restart it — it resumes where it stopped.
- Every weekday at **18:30 PKT** it runs the evening update: new session,
  corporate-action adjustment, index levels, payouts, announcements, and fresh
  fundamentals for every company that just filed results (~40 PSX requests).
  If PSX is unreachable it retries every 30 minutes, up to 4 times.
- Every **Saturday 10:00 PKT**: full fundamentals refresh, re-check of recent
  holidays, data-quality report.
- After every job it writes `data/status.json` (what ran, whether it worked,
  what runs next) — `mbf status` prints it; the website's health page will
  show it.

In step 5 this process is packaged as a container next to the web app, so a
deploy is "start the container" and that's it.

**Testing on a laptop** (which sleeps, so a long-running process is awkward):
register the evening update once with Windows Task Scheduler — see the
`schtasks` line at the top of `scripts/run_daily.ps1`. The first run
bootstraps if needed.

**One-shot / debugging:** `mbf bootstrap`, `mbf update [--full-sweep]`, and the
individual stages (`backfill-prices`, `adjust`, `company-sweep`, `events`,
`quality`, …) — see `python -m mbf --help`.

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
  from a one-time import of earlier AKD pulls (`legacy/akd_data`, optional:
  the scheduler imports it automatically if the files are present).
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
