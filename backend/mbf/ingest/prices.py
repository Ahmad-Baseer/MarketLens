"""Daily OHLCV for every PSX symbol, from POST /historical (one request per day)."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from mbf import config, store
from mbf.psx.client import PSXClient, PSXError
from mbf.psx.parsers import parse_historical

log = logging.getLogger(__name__)

# PSX's day is final well after the close (Mon-Thu 15:30, Fri 16:30 PKT).
SESSION_FINAL_HOUR = 18


def last_closed_session(now: datetime | None = None) -> date:
    now = now or datetime.now(ZoneInfo(config.TZ))
    d = now.date() if now.hour >= SESSION_FINAL_HOUR else now.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _is_session(df: pd.DataFrame) -> bool:
    """A real session has traded stocks. PSX sometimes answers a trading day
    with an empty table (transient: 6 such days found by the KSE-100 calendar
    check) and some holidays with a handful of untraded futures rows."""
    if df.empty:
        return False
    stock = (df["row_type"] == "equity") & ~df["symbol"].str.contains("-", regex=False)
    return bool((stock & (df["volume"] > 0)).any())


def fetch_day(client: PSXClient, d: date, retries: int = 2) -> int:
    df = parse_historical(client.historical(d), d)
    for _ in range(retries):
        if _is_session(df):
            break
        time.sleep(3)                                  # empty answers can be transient
        df = parse_historical(client.historical(d), d)
    if not _is_session(df):
        store.mark_holiday(d)
        return 0
    store.write_parquet(df, store.day_file(d))
    if store.holiday_file(d).exists():
        store.holiday_file(d).unlink()
    return len(df)


def backfill(client: PSXClient, start: date, end: date, refetch: set[date] | None = None,
             progress_every: int = 50) -> dict:
    """Fetch every weekday in [start, end] not already on disk (plus `refetch`)."""
    days = [d.date() for d in pd.bdate_range(start, end)]
    todo = [d for d in days if not store.day_done(d) or (refetch and d in refetch)]
    log.info("prices: %d weekdays in range, %d to fetch", len(days), len(todo))
    t0, rows, holidays, failed = time.monotonic(), 0, 0, []
    for i, d in enumerate(todo, 1):
        if store.day_done(d) and not (refetch and d in refetch):
            continue                     # another worker got there first
        try:
            n = fetch_day(client, d)
            rows += n
            holidays += n == 0
        except PSXError as e:
            log.warning("prices: %s failed: %s", d, e)
            failed.append(d)
        if i % progress_every == 0 or i == len(todo):
            el = time.monotonic() - t0
            eta = el / i * (len(todo) - i)
            log.info("prices: %d/%d (%.1f%%) last=%s rows=%s holidays=%d failed=%d eta=%dm%02ds",
                     i, len(todo), 100 * i / len(todo), d, f"{rows:,}", holidays, len(failed),
                     eta // 60, eta % 60)
    if failed:                                   # one retry pass for transient errors
        log.info("prices: retrying %d failed days", len(failed))
        still = []
        for d in failed:
            try:
                fetch_day(client, d)
            except PSXError:
                still.append(d)
        failed = still
    return {"fetched": len(todo), "rows": rows, "holidays": holidays, "failed": failed}


def update(client: PSXClient, refetch_last: int = 3) -> dict:
    """Bring the store up to the last closed session. Re-fetches the last few
    trading days too, in case PSX revised them after we first pulled."""
    trading, holidays = store.fetched_days()
    end = last_closed_session()
    start = (trading[-1] + timedelta(days=1)) if trading else config.HISTORY_START
    refetch = set(trading[-refetch_last:]) if trading else set()
    refetch |= {d for d in holidays if d >= end - timedelta(days=14)}   # recent "holidays" too
    if refetch:
        start = min(start, min(refetch))
    return backfill(client, start, end, refetch=refetch)


def demote_non_sessions() -> list[date]:
    """Stored days with no traded stock (e.g. 2021-10-19: five untraded futures
    rows on a public holiday) become holiday markers. Local only."""
    trading, _ = store.fetched_days()
    demoted = []
    for d in trading:
        if not _is_session(pd.read_parquet(store.day_file(d))):
            store.mark_holiday(d)
            demoted.append(d)
    log.info("demoted %d stored days with no trades: %s", len(demoted), demoted[:10])
    return demoted


def recheck_holidays(client: PSXClient, since: date | None = None) -> list[date]:
    """Re-request every day marked as a holiday; returns those that turned out
    to be sessions (and are now stored)."""
    demote_non_sessions()
    _, holidays = store.fetched_days()
    todo = [d for d in holidays if since is None or d >= since]
    log.info("recheck: %d holiday markers", len(todo))
    recovered = []
    for i, d in enumerate(todo, 1):
        if fetch_day(client, d, retries=1):
            recovered.append(d)
            log.info("recheck: %s was a trading day", d)
        if i % 50 == 0:
            log.info("recheck: %d/%d, recovered %d", i, len(todo), len(recovered))
    return recovered


def compact() -> pd.DataFrame:
    """Concatenate all day files into prices/daily_raw.parquet."""
    root = config.DATA_DIR / "raw" / "historical"
    files = sorted(root.glob("*/*.parquet"))
    if not files:
        raise FileNotFoundError("no daily price files yet — run the backfill first")
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    df = (df.sort_values(["symbol", "date"])
            .drop_duplicates(["symbol", "date"], keep="last")
            .reset_index(drop=True))
    store.write_parquet(df, store.path("prices", "daily_raw.parquet"))
    log.info("prices: compacted %d files -> %s rows, %d symbols, %s..%s", len(files),
             f"{len(df):,}", df["symbol"].nunique(), df["date"].min().date(), df["date"].max().date())
    return df
