"""Payout announcements and company announcements (titles + PDF links)."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from mbf import store
from mbf.psx.client import PSXClient, PSXError
from mbf.psx.parsers import parse_announcements, parse_payouts

log = logging.getLogger(__name__)

PAGE = 50


def update_payouts(client: PSXClient, max_pages: int = 80) -> pd.DataFrame:
    """Market-wide payout feed (PSX keeps ~18 months). Stops early once a page
    contains nothing newer than what we already hold."""
    p = store.path("events", "payouts.parquet")
    old = store.read_parquet(p)
    newest = old["announced_at"].max() if not old.empty else None
    pages = []
    for i in range(max_pages):
        df = parse_payouts(client.payouts(count=PAGE, offset=i * PAGE))
        if df.empty:
            break
        pages.append(df)
        if newest is not None and df["announced_at"].max() < newest - pd.Timedelta(days=7):
            break
    new = pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()
    allp = pd.concat([old, new], ignore_index=True) if not old.empty else new
    if not allp.empty:
        allp = (allp.drop_duplicates(["symbol", "details", "announced_at", "component"], keep="last")
                    .sort_values("announced_at").reset_index(drop=True))
        store.write_parquet(allp, p)
    log.info("payouts: %d rows (%d fetched this run)", len(allp), len(new))
    return allp


def _months(start: date, end: date):
    d = start.replace(day=1)
    while d <= end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(d, start), min(nxt - timedelta(days=1), end)
        d = nxt


def update_announcements(client: PSXClient, since: date, until: date) -> pd.DataFrame:
    p = store.path("events", "announcements.parquet")
    old = store.read_parquet(p)
    frames, requests = [], 0
    for a, b in _months(since, until):
        off = 0
        while True:
            try:
                df = parse_announcements(client.announcements(a, b, offset=off, count=PAGE))
            except PSXError as e:
                log.warning("announcements %s..%s offset %d: %s", a, b, off, e)
                break
            requests += 1
            frames.append(df)
            if len(df) < PAGE:
                break
            off += PAGE
        log.info("announcements: %s done (%d requests so far)", a.strftime("%Y-%m"), requests)
    new = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    allr = pd.concat([old, new], ignore_index=True) if not old.empty else new
    if not allr.empty:
        allr = (allr.drop_duplicates(["symbol", "announced_at", "title", "doc_id"], keep="last")
                    .sort_values("announced_at").reset_index(drop=True))
        store.write_parquet(allr, p)
    log.info("announcements: %d rows total (%d fetched)", len(allr), len(new))
    return allr
