# MBF — PSX signal provider

Short-horizon (1 day – 1 week) signals for Pakistan Stock Exchange equities,
backed by fundamentals and technicals, with a fully transparent track record.

**Status:** steps 1–4 of 5 — data foundation, signal research, live signal engine, web app.
Deployment comes next.

```
backend/      Python package `mbf`
  mbf/psx/      client (request key, rate limit, retries) + HTML parsers
  mbf/ingest/   prices, reference data, company fundamentals, events, notices, AKD seed
  mbf/research/ backtest harness, event studies, signal scoreboard
  mbf/signals/  live engine: calendar, par values, dividend run-up, warnings,
                ledger (published signals + outcomes), web JSON
  tests/        parser, adjustment, outcome and signal tests
data/         Parquet store (not in git) — see backend/mbf/store.py for layout
  ledger/       published signals (append-only), backtest, outcomes, warnings
  web/          the JSON the website serves: today.json, history.json, signals/<id>.json
web/          Next.js site (MarketLens) that reads data/web — see web/README.md
reports/      data_quality.md, research_step2.md, research_new_data.md, extractor_baseline.md
legacy/       the previous screener, research and AKD CSV pulls (kept for reference)
```

## Setting up on a new Windows PC

1. **Install Python 3.11+** from https://www.python.org/downloads/ (tick *Add python.exe
   to PATH*) and **Node.js 20.9+** (the LTS) from https://nodejs.org/.
2. **Clone the repo:** `git clone https://github.com/Ahmad-Baseer/MarketLens.git`
3. **If you have access to the old PC's data, copy its `data` folder across** (USB
   drive, cloud folder, …). `data/` is not in git, and it holds the only copy of the
   **live signal record** and the price, fundamentals and dividend history.
   **No access to it?** Skip this step and leave `-DataFrom` out in step 4: see
   [Starting without the old PC's data](#starting-without-the-old-pcs-data).
4. **Run the setup**, in PowerShell from the repo folder:

   ```
   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Startup -DataFrom E:\data
   ```

   - `-Startup` starts the tray icon when you log in to Windows; `-NoStartup` doesn't.
     With neither, the script asks.
   - `-DataFrom` is where you put the copied `data` folder (left out if you skipped
     step 3).
5. **Done.** The MarketLens icon sits by the clock (maybe under the ^ arrow);
   left-click it to open the website.

The setup creates `.venv` and installs the Python packages, installs the website's
packages and builds it, registers the three scheduled jobs, and sets up and starts the
tray icon. With `-DataFrom`, the new PC works exactly like the old one straight away.

Re-running the setup is safe. It is also the fix after moving the project folder, which
breaks the Python install and the scheduled jobs.

### Starting without the old PC's data

Nothing extra to do: run the setup without `-DataFrom` and it starts the first data
download from PSX by itself when it finishes. That takes 4–5 hours in the background and
carries on by itself if the PC sleeps or restarts (the tray icon is blue while it runs;
progress in `data\logs\weekly_<date>.log`). The site fills in once it's done.

What you don't get back this way:
- **The live signal record** starts empty: it exists only in the old `data` folder.
- **The dividend history** only goes back to November 2024, when PSX's payout feed
  starts. If you have a copy of the old `legacy\akd_data` folder (also not in git), put
  it in `legacy\` before running the setup and the history goes back to 2018.

## Running it — nothing is manual

**Production (server):** one long-running process does everything.

```
.venv\Scripts\python -m mbf scheduler
```

- On first start with an empty `data/` it **bootstraps** the whole store
  (~2–3 hours: 26 years of prices, fundamentals, announcements). Interrupted?
  Restart it — it resumes where it stopped.
- Every weekday at **18:30 PKT** it runs the evening update: new session,
  corporate-action adjustment, index levels, payouts, announcements, PSX notices
  and holidays, fresh fundamentals for every company that just filed results
  (~40 PSX requests) — then the **signal run**: publish tonight's signals to the
  ledger, replay the backtest, update every signal's outcome, compute warnings and
  write `data/web/*.json`. If PSX is unreachable it retries every 30 minutes, up to 4 times.
- Every **Saturday 10:00 PKT**: full fundamentals refresh, re-check of recent
  holidays, data-quality report.
- After every job it writes `data/status.json` (what ran, whether it worked,
  what runs next) — `mbf status` prints it; the website's health page will
  show it.

In step 5 this process is packaged as a container next to the web app, so a
deploy is "start the container" and that's it.

**On a laptop until deployment** (it sleeps, so a long-running process is awkward):
`powershell -File scripts\register_tasks.ps1` registers three Windows scheduled tasks
for the current user: "MarketLens evening update" (Mon–Fri 18:30), "MarketLens
weekly maintenance" (Sat 10:00) and "MarketLens catch-up check" (hourly and at logon).
The check runs whichever job has no run on record since its last scheduled time
(`mbf due`), covering a start Windows missed while the laptop slept and a run that
sleep cut off; otherwise it exits in about a second. All run on battery and retry
3 times 30 minutes apart; logs go to `data\logs\`. The first run bootstraps if needed.

**Tray icon** (`backend/mbf/tray.py`; `.venv\Scripts\pythonw.exe -m mbf.tray`, set up by
`setup.ps1`). Left-click opens the website, starting it if needed: the production build
on http://localhost:3200, this computer only, rebuilt first when the web code changed.
The port is set in one place, the `start` script in `web/package.json`; the tray reads
it from there.
Right-click: start/stop the website, **check scheduled jobs now** (runs a missed evening
or weekly job, then opens the site), the latest signals and open positions, recent runs
(click one for its log), run the evening update now, stop the running job, open the
latest log or the data folder, pause scheduled jobs, start with Windows. The icon is
green when the data is up to date, blue while a job runs, amber when a scheduled run was
missed, red when the last run failed and grey while paused. Notifications cover new
signals, failed runs, catch-ups and the end of anything started from the menu. Its own
log: `data\logs\tray.log`; the website's: `data\logs\web.log`. Start with Windows on/off
from a terminal: `.venv\Scripts\python -m mbf.tray --startup on|off`.

**One-shot / debugging:** `mbf bootstrap`, `mbf update [--full-sweep]`, and the
individual stages (`backfill-prices`, `adjust`, `company-sweep`, `events`,
`quality`, `signals [--dry-run]`, …) — see `python -m mbf --help`. Use
`signals --dry-run` for testing: it computes tonight's signals without adding them
to the live ledger.

## The signals

Only one signal family survived the research (`reports/research_step2.md`,
`reports/research_new_data.md`): the **dividend run-up** (`DIV_K5`). When a cash
dividend worth 2–7% of the price has been announced for a top-200 liquid stock, buy
in the last 30 minutes of the session 5 sessions before the ex-date (only up to
1 ATR above the signal close), keep a protective stop 3 ATR below, and sell at the
ex-date's opening auction with the dividend collected. Replayed day by day since
2018: 584 signals, 59% winners, +0.69% average after 0.6% costs and 15% tax.

- **Published signals are immutable.** Each evening's signals are written once to
  `data/ledger/published/<date>.json` and appended to `signals.parquet`; outcomes
  are recomputed from prices but the signal itself never changes.
- **Ex-dates are predicted** from the book-closure dates in PSX's payout feed
  (book-closure start minus one session under T+1, two before 2026-02-09) on a
  calendar that knows PSX's announced holidays (read from PSX's holiday notices).
- **Dividends are announced as % of par**; par comes from PSX's own ex-date
  price drops (dividend ÷ % announced), then the AKD profiles, then Rs 10.
- **Warnings** (shown, never traded): just went ex-dividend, weak close on a big
  drop, volume spike, PSX unusual-movement letter, leaving KSE-30.
- The "early dividend entry" variant (buy right after the announcement) is
  computed in the backtest but not published: replayed faithfully it falls short
  of the research bar.

## The website

```
.venv\Scripts\python -m mbf signals --dry-run   # only needed if data/web doesn't exist yet
cd web && npm install && npm run dev            # http://localhost:3200
OR
npm --prefix web run dev
```

Details, configuration and the invite-code gate: `web/README.md`.

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
