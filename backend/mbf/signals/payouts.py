"""Cash-dividend announcements in one schema, for live signals and for replaying
history.

Live: PSX's payout feed (from Nov 2024; % of par + book-closure dates; the
ex-date is predicted from the book closure exactly as a trader would).
History before the feed: the AKD seed, re-dated to PSX's actual ex-date. AKD has
announcement dates without a time, so the backtest treats an announcement as
known at that day's close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mbf import config, store
from mbf.signals import par as parmod

COLUMNS = ["symbol", "announced_at", "div_rs", "div_pct", "par", "has_bonus", "has_right",
           "bc_from", "bc_to", "ex_date", "ex_basis", "source", "details"]


def ex_from_book_closure(bc_from: pd.Timestamp, sessions: pd.DatetimeIndex) -> pd.Timestamp | None:
    return parmod.ex_date_for(bc_from, sessions)


def psx_feed(sessions: pd.DatetimeIndex) -> pd.DataFrame:
    p = store.read_parquet(store.path("events", "payouts.parquet"))
    if p.empty:
        return pd.DataFrame(columns=COLUMNS)
    p = p.dropna(subset=["book_closure_from"])
    key = ["symbol", "announced_at", "book_closure_from"]
    g = p.groupby(key, as_index=False).agg(
        div_pct=("pct", lambda s: s[p.loc[s.index, "kind"] == "dividend"].sum(min_count=1)),
        has_bonus=("kind", lambda k: (k == "bonus").any()),
        has_right=("kind", lambda k: (k == "right").any()),
        bc_to=("book_closure_to", "max"), details=("details", "first"))
    g = g[g["div_pct"].notna() & (g["div_pct"] > 0)]
    g["par"] = parmod.lookup(g["symbol"]).to_numpy()
    g["div_rs"] = g["div_pct"] / 100 * g["par"]
    g["ex_date"] = [ex_from_book_closure(b, sessions) for b in g["book_closure_from"]]
    g = g.rename(columns={"book_closure_from": "bc_from"})
    g["ex_basis"] = "book_closure"
    g["source"] = "psx"
    return g[COLUMNS]


def akd_history(before: pd.Timestamp) -> pd.DataFrame:
    """AKD payouts announced before `before`, dated to PSX's actual ex-date adjustment."""
    ak = store.read_parquet(store.path("seed", "akd", "payout_events.parquet"))
    ca = store.read_parquet(store.path("prices", "corporate_actions.parquet"))
    if ak.empty or ca.empty:
        return pd.DataFrame(columns=COLUMNS)
    ca = ca[ca["applied"]][["symbol", "date"]].rename(columns={"date": "x_psx"})
    m = ak.merge(ca, on="symbol")
    m = m[(m["x_psx"] - m["ex_date"]).abs() <= pd.Timedelta(days=10)]
    m["d"] = (m["x_psx"] - m["ex_date"]).abs()
    m = m.sort_values("d").drop_duplicates(["symbol", "ex_date"])
    m = m[(m["div_rs"] > 0) & (m["announce_date"] < before)]
    out = pd.DataFrame({
        "symbol": m["symbol"],
        # AKD dates carry no time: known by that evening
        "announced_at": m["announce_date"].dt.normalize() + pd.Timedelta(hours=17),
        "div_rs": m["div_rs"], "div_pct": np.nan, "par": parmod.lookup(m["symbol"]).to_numpy(),
        "has_bonus": m["bonus_r"] > 0, "has_right": m["right_r"] > 0,
        "bc_from": m["bc_from"], "bc_to": m["bc_to"], "ex_date": m["x_psx"],
        "ex_basis": "psx_adjustment", "source": "akd", "details": None})
    out["div_pct"] = out["div_rs"] / out["par"] * 100
    return out[COLUMNS]


def all_events(sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """sessions: past AND predicted future sessions (Calendar.all), so that upcoming
    book closures map to their future ex-dates."""
    live = psx_feed(sessions)
    start = live["announced_at"].min() if not live.empty else pd.Timestamp.max
    hist = akd_history(start)
    ev = pd.concat([hist, live], ignore_index=True)
    ev = ev.dropna(subset=["ex_date"])
    ev["ex_date"] = pd.to_datetime(ev["ex_date"])
    return ev.sort_values("announced_at").reset_index(drop=True)
