"""Per-company fundamentals snapshot from /company/{SYM} (+ report list).

Every sweep is stored under its date, and every reported figure is also kept
in a cumulative table with the date we first saw it. That is what makes
fundamentals point-in-time: a backtest can only use a number on or after the
day it actually appeared.
"""
from __future__ import annotations

import logging
import time
from datetime import date

import pandas as pd

from mbf import config, store
from mbf.psx.client import PSXClient, PSXError
from mbf.psx.parsers import parse_company, parse_company_reports

log = logging.getLogger(__name__)

# The report list is a separate PSX page that can go down on its own (2026-10-23: HTTP 500
# for every company while the company pages were fine). Each failure costs ~35 s of client
# retries, which across a 760-company weekly sweep would overrun the job's time limit.
REPORTS_GIVE_UP = 3          # consecutive report-list failures before the sweep stops asking


def sweep(client: PSXClient, symbols: list[str], with_reports: bool = True,
          snapshot_date: date | None = None, progress_every: int = 50) -> dict:
    snap = snapshot_date or pd.Timestamp.now(tz=config.TZ).date()
    info, quote, equity, fins, ratios, reports, failed = [], [], [], [], [], [], []
    reports_failed, in_a_row = [], 0
    t0 = time.monotonic()
    for i, s in enumerate(symbols, 1):
        try:
            c = parse_company(client.company(s), s)
            info.append(c["info"]); quote.append(c["quote"]); equity.append(c["equity"])
            fins.append(c["financials"]); ratios.append(c["ratios"])
        except PSXError as e:
            log.warning("company %s: %s", s, e)
            failed.append(s)
            c = None
        except Exception as e:                       # a parser surprise must not kill the sweep
            log.exception("company %s: unexpected %s", s, e)
            failed.append(s)
            c = None
        # the company's figures are already in hand: a missing report list doesn't fail it
        if c is not None and with_reports:
            try:
                reports.append(parse_company_reports(client.company_reports(s), s))
                in_a_row = 0
            except Exception as e:
                log.warning("company %s reports: %s", s, e)
                reports_failed.append(s)
                in_a_row += 1
                if in_a_row >= REPORTS_GIVE_UP:
                    with_reports = False
                    log.warning("reports: %d failures in a row, not asking for report lists "
                                "for the rest of this sweep", in_a_row)
        if i % progress_every == 0 or i == len(symbols):
            el = time.monotonic() - t0
            log.info("company: %d/%d failed=%d eta=%dm", i, len(symbols), len(failed),
                     el / i * (len(symbols) - i) // 60)

    d = snap.isoformat()
    swept = set(symbols) - set(failed)
    out = {}
    for name, rows in (("info", info), ("quote", quote), ("equity", equity)):
        df = pd.DataFrame(rows)
        df["snapshot"] = pd.Timestamp(snap)
        out[name] = len(_upsert(df, store.path("fundamentals", "snapshots", d, f"{name}.parquet"), swept))
    for name, parts in (("financials", fins), ("ratios", ratios)):
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        df["snapshot"] = pd.Timestamp(snap)
        out[name] = len(_upsert(df, store.path("fundamentals", "snapshots", d, f"{name}.parquet"), swept))
        _merge_first_seen(df, name)
    if reports:
        _merge_reports(pd.concat(reports, ignore_index=True))
    out["failed"] = failed
    out["reports_failed"] = len(reports_failed)
    out["reports_skipped"] = len(symbols) - len(failed) - len(reports) - len(reports_failed)
    log.info("company sweep %s: %s", d, {k: v for k, v in out.items() if k != "failed"})
    return out


def _upsert(df: pd.DataFrame, p, swept: set[str]) -> pd.DataFrame:
    """A partial sweep (e.g. the evening run re-reading 10 companies that just
    filed) must replace only those companies in the day's snapshot, not wipe
    the other ~750."""
    old = store.read_parquet(p)
    if not old.empty:
        df = pd.concat([old[~old["symbol"].isin(swept)], df], ignore_index=True)
    store.write_parquet(df, p)
    return df


def _merge_first_seen(df: pd.DataFrame, name: str):
    """Cumulative table: one row per distinct reported value, stamped with the
    first snapshot it appeared in (restatements show up as new rows)."""
    if df.empty:
        return
    p = store.path("fundamentals", f"{name}_history.parquet")
    new = df.rename(columns={"snapshot": "first_seen"})
    old = store.read_parquet(p)
    allr = pd.concat([old, new], ignore_index=True) if not old.empty else new
    allr = (allr.sort_values("first_seen")
                .drop_duplicates(["symbol", "kind", "period", "item", "value"], keep="first"))
    store.write_parquet(allr.reset_index(drop=True), p)


def _merge_reports(df: pd.DataFrame):
    p = store.path("fundamentals", "reports.parquet")
    old = store.read_parquet(p)
    allr = pd.concat([old, df], ignore_index=True) if not old.empty else df
    allr = allr.drop_duplicates(["symbol", "report_id"], keep="last").reset_index(drop=True)
    store.write_parquet(allr, p)
    log.info("reports: %d PDFs listed across %d companies", len(allr), allr["symbol"].nunique())
