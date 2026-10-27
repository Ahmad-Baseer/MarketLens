"""Unattended operation: nobody runs commands by hand in production.

    python -m mbf scheduler

is the only thing a server (or a laptop during testing) needs to run. It:
  * bootstraps the data store on first start (resumable — an interrupted
    bootstrap picks up where it stopped);
  * runs the evening update every weekday after the PSX close, retrying if
    PSX is unreachable;
  * runs weekly maintenance on Saturday morning;
  * writes data/status.json after every job, which the website's health page
    reads.
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from mbf import config, store

log = logging.getLogger(__name__)

TZ = ZoneInfo(config.TZ)
DAILY_AT = (18, 30)          # weekdays, PKT — the session is final well before this
WEEKLY_AT = (10, 0)          # Saturday, PKT
RETRY_EVERY_MIN = 30
RETRIES = 4
ANNOUNCEMENTS_SINCE = date(2024, 1, 1)


# ------------------------------------------------------------------- jobs
def bootstrap() -> dict:
    """Bring an empty (or partial) store to a complete state. Every stage is
    skipped if its output already exists, so this is cheap once done."""
    from mbf import adjust, market, quality
    from mbf.ingest import akd_seed, company, events, prices, reference
    from mbf.psx.client import PSXClient

    done = {}
    with PSXClient() as c:
        res = prices.backfill(c, config.HISTORY_START, prices.last_closed_session())
        done["prices_fetched"] = res["fetched"]
        prices.compact()
        if not store.path("ref", "symbols.parquet").exists():
            reference.update_symbols(c)
            reference.update_market_watch(c)
            reference.update_indices(c)
        if not any((config.DATA_DIR / "fundamentals" / "snapshots").glob("*")):
            company.sweep(c, reference.equity_symbols(), with_reports=True)
        if not store.path("events", "announcements.parquet").exists():
            events.update_payouts(c)
            events.update_announcements(c, ANNOUNCEMENTS_SINCE, prices.last_closed_session())
        if not store.path("events", "psx_notices.parquet").exists():
            events.update_notices(c, full=True)
        if not store.path("ref", "holidays.parquet").exists():
            from mbf.signals import calendar as sigcal
            sigcal.update_holidays(c)
    if (not store.path("seed", "akd", "statements.parquet").exists()
            and (config.LEGACY_AKD_DIR / "mbf_statements.csv").exists()):
        akd_seed.run()                       # optional: only if the legacy files are present
    daily, _ = adjust.run()
    market.build(daily)
    quality.run()
    return done


def daily_update(full_sweep: bool = False) -> dict:
    from mbf import adjust, market
    from mbf.ingest import company, events, intraday, prices, reference
    from mbf.psx.client import PSXClient

    with PSXClient() as c:
        # intraday ticks exist only for the current session: grab them first,
        # but only once the session is over (the job runs after 18:00 PKT)
        if datetime.now(TZ).date() == prices.last_closed_session():
            try:
                intraday.capture(c)
            except Exception as e:                           # never block the update on this
                log.warning("intraday capture failed: %s", e)
        res = prices.update(c)
        prices.compact()
        daily, _ = adjust.run()
        market.build(daily)
        reference.update_symbols(c)
        reference.update_market_watch(c)
        reference.update_indices(c)
        events.update_payouts(c)
        events.update_notices(c)
        from mbf.signals import calendar as sigcal
        sigcal.update_holidays(c)
        last = prices.last_closed_session()
        ann = events.update_announcements(c, last - timedelta(days=5), last)
        recent = ann[(ann["announced_at"] >= str(last - timedelta(days=5)))
                     & ann["title"].str.contains("financial result", case=False, na=False)]
        eq = reference.equity_symbols()
        syms = eq if full_sweep else sorted(set(recent["symbol"]) & set(eq))
        sw = company.sweep(c, syms, with_reports=True) if syms else {}
        requests = c.requests
    from mbf.signals import engine
    sig = engine.run_evening(daily)
    return {"prices": {k: (v if k != "failed" else [str(d) for d in v]) for k, v in res.items()},
            "companies_refreshed": len(syms) - len(sw.get("failed", [])),
            "companies_failed": sw.get("failed", []),
            "report_lists_missing": sw.get("reports_failed", 0) + sw.get("reports_skipped", 0),
            "psx_requests": requests,
            "last_session": str(last), "signals": sig}


def weekly_maintenance() -> dict:
    from mbf import quality
    from mbf.ingest import prices
    from mbf.psx.client import PSXClient

    out = daily_update(full_sweep=True)
    with PSXClient() as c:
        rec = prices.recheck_holidays(c, since=date.today() - timedelta(days=60))
    if rec:
        prices.compact()
    quality.run()
    out["holidays_recovered"] = [str(d) for d in rec]
    from mbf.signals import engine, par
    par.build(engine._sessions(engine._daily()))
    return out


# ----------------------------------------------------------------- status
def _status_path():
    return config.DATA_DIR / "status.json"


def read_status() -> dict:
    p = _status_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _record(job: str, ok: bool, started: datetime, detail, next_run: datetime | None):
    st = read_status()
    st[job] = {"ok": ok, "started": started.isoformat(timespec="seconds"),
               "finished": datetime.now(TZ).isoformat(timespec="seconds"), "detail": detail}
    if next_run:
        st["next_run"] = next_run.isoformat(timespec="seconds")
    _status_path().parent.mkdir(parents=True, exist_ok=True)
    _status_path().write_text(json.dumps(st, indent=2, default=str), encoding="utf-8")


def run_job(name: str, fn, retries: int = 0, next_run: datetime | None = None) -> bool:
    for attempt in range(retries + 1):
        started = datetime.now(TZ)
        log.info("job %s: start (attempt %d)", name, attempt + 1)
        try:
            detail = fn()
            _record(name, True, started, detail, next_run)
            log.info("job %s: ok %s", name, detail)
            return True
        except Exception as e:                       # keep the scheduler alive
            log.error("job %s failed: %s", name, e)
            _record(name, False, started, {"error": str(e), "trace": traceback.format_exc()[-2000:]},
                    next_run)
            if attempt < retries:
                time.sleep(RETRY_EVERY_MIN * 60)
    return False


# -------------------------------------------------------------- scheduler
def next_runs(now: datetime) -> list[tuple[datetime, str]]:
    """Upcoming (time, job) pairs within the next 8 days, soonest first."""
    out = []
    for i in range(8):
        d = (now + timedelta(days=i)).date()
        if d.weekday() < 5:
            out.append((datetime(d.year, d.month, d.day, *DAILY_AT, tzinfo=TZ), "daily_update"))
        if d.weekday() == 5:
            out.append((datetime(d.year, d.month, d.day, *WEEKLY_AT, tzinfo=TZ), "weekly_maintenance"))
    return sorted(t for t in out if t[0] > now)


def needs_bootstrap() -> bool:
    return not (store.path("prices", "daily.parquet").exists()
                and any((config.DATA_DIR / "fundamentals" / "snapshots").glob("*"))
                and store.path("events", "announcements.parquet").exists())


def scheduler(run_now: bool = False):
    jobs = {"daily_update": daily_update, "weekly_maintenance": weekly_maintenance}
    if needs_bootstrap():
        log.info("scheduler: data store incomplete — bootstrapping first (resumable)")
        run_job("bootstrap", bootstrap, retries=RETRIES)
    elif run_now:
        run_job("daily_update", daily_update, retries=1)
    while True:
        when, job = next_runs(datetime.now(TZ))[0]
        log.info("scheduler: next %s at %s", job, when.isoformat(timespec="minutes"))
        _record("scheduler", True, datetime.now(TZ), {"waiting_for": job}, when)
        while datetime.now(TZ) < when:
            time.sleep(min(60, max(1, (when - datetime.now(TZ)).total_seconds())))
        following = next_runs(when + timedelta(minutes=1))[0][0]
        run_job(job, jobs[job], retries=RETRIES, next_run=following)
