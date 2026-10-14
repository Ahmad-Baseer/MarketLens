"""Save each day's intraday ticks for the most-traded stocks.

PSX only serves the current session (/timeseries/int/{SYM}: [unix_ts, price,
volume] from the 09:30 opening auction to the post-close session). Keeping them
lets us measure, from real prints, how much size the opening auction and the
closing half-hour (PSX's close = VWAP of the last 30 minutes) actually absorb —
the basis for realistic trading costs and the entry/exit instructions.
"""
from __future__ import annotations

import logging

import pandas as pd

from mbf import config, store
from mbf.psx.client import PSXClient, PSXError

log = logging.getLogger(__name__)

TOP_N = 150


def most_traded(n: int = TOP_N) -> list[str]:
    mw = store.read_parquet(store.path("ref", "market_watch.parquet"))
    if mw.empty:
        return []
    mw = mw[~mw["symbol"].str.contains("-", regex=False)]
    mw = mw.assign(value=mw["current"] * mw["volume"]).sort_values("value", ascending=False)
    return mw["symbol"].head(n).tolist()


def capture(client: PSXClient, symbols: list[str] | None = None) -> int:
    symbols = symbols or most_traded()
    frames = []
    for s in symbols:
        try:
            j = client._request("GET", f"/timeseries/int/{s}").json()
        except PSXError as e:
            log.warning("intraday %s: %s", s, e)
            continue
        d = j.get("data") or []
        if not d:
            continue
        t = pd.DataFrame([r[:3] for r in d], columns=["ts", "price", "volume"])
        t["symbol"] = s
        frames.append(t)
    if not frames:
        return 0
    df = pd.concat(frames, ignore_index=True)
    df["time"] = (pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(config.TZ)
                  .dt.tz_localize(None))
    day = df["time"].dt.date.mode().iat[0]
    df = df.sort_values(["symbol", "time"]).drop(columns="ts")
    store.write_parquet(df, store.path("intraday", f"{day.isoformat()}.parquet"))
    log.info("intraday: %d ticks for %d symbols on %s", len(df), df["symbol"].nunique(), day)
    return len(df)
