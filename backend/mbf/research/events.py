"""Point-in-time company events for research (2018+, from the AKD seed; PSX
announcements take over for live use).

Timing rule: AKD records announcement DATES only (no time). PSX timestamps
(2024+) show ~98% of results are filed during or before market hours, the rest
shortly after the close. So an event dated D is acted on at the close of the
first session on/after D at the earliest, and entered at the next open — the
information is always public by then.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mbf import store


def _sessions(f: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(np.sort(f["date"].unique()))


def snap_to_session(dates: pd.Series, sessions: pd.DatetimeIndex, offset: int = 0) -> pd.Series:
    """First session on/after each date, shifted by `offset` sessions."""
    i = sessions.searchsorted(dates.values) + offset
    ok = (i >= 0) & (i < len(sessions))
    out = pd.Series(pd.NaT, index=dates.index, dtype="datetime64[ns]")
    out[ok] = sessions[i[ok]]
    return out


def earnings(f: pd.DataFrame) -> pd.DataFrame:
    """One row per results filing with a same-period-last-year comparison."""
    a = store.read_parquet(store.path("seed", "akd", "announcements.parquet"))
    fr = a[a["announcementType"].str.startswith("FR", na=False)].dropna(
        subset=["unconsolidatedQuarterEps", "periodEndDate"]).copy()
    fr["annual"] = fr["announcementType"].str.startswith("FRYE")
    fr = fr.rename(columns={"date": "ann_date", "unconsolidatedQuarterEps": "eps",
                            "unconsolidatedSales": "sales", "unconsolidatedPat": "pat"})
    fr["pm"], fr["py"] = fr["periodEndDate"].dt.month, fr["periodEndDate"].dt.year
    fr = (fr.sort_values("ann_date")
            .drop_duplicates(["symbol", "py", "pm", "annual"], keep="first"))
    prev = fr[["symbol", "py", "pm", "annual", "eps", "sales", "pat"]].copy()
    prev["py"] += 1
    m = fr.merge(prev, on=["symbol", "py", "pm", "annual"], how="left", suffixes=("", "_prev"))
    m = m.dropna(subset=["eps_prev"])
    m["eps_delta"] = m["eps"] - m["eps_prev"]
    with np.errstate(divide="ignore", invalid="ignore"):
        m["sales_g"] = m["sales"] / m["sales_prev"] - 1
        m["pat_g"] = (m["pat"] - m["pat_prev"]) / m["pat_prev"].abs()
    m["turnaround"] = (m["eps"] > 0) & (m["eps_prev"] <= 0)
    # profit growth not backed by sales: the classic one-off / other-income jump
    m["oneoff_flag"] = (m["pat_g"] > 0.3) & (m["sales_g"].fillna(0) < 0.05)
    s = _sessions(f)
    m["d0"] = snap_to_session(m["ann_date"], s, 0)
    px = f[["symbol", "date", "close"]].rename(columns={"date": "d0", "close": "close_d0"})
    m = m.merge(px, on=["symbol", "d0"], how="left")
    m["surprise"] = m["eps_delta"] / m["close_d0"]
    return m[["symbol", "ann_date", "d0", "annual", "periodEndDate", "eps", "eps_prev", "eps_delta",
              "surprise", "sales_g", "pat_g", "turnaround", "oneoff_flag", "close_d0"]].dropna(subset=["d0"])


def payouts(f: pd.DataFrame) -> pd.DataFrame:
    """AKD payout events re-dated to PSX's actual ex-date (LDCP adjustment).
    AKD's own ex-date is usually one session late."""
    ak = store.read_parquet(store.path("seed", "akd", "payout_events.parquet"))
    ev = store.read_parquet(store.path("prices", "corporate_actions.parquet"))
    ev = ev[ev["applied"]][["symbol", "date", "factor"]].rename(columns={"date": "x_psx"})
    m = ak.merge(ev, on="symbol", how="inner")
    m = m[(m["x_psx"] - m["ex_date"]).abs() <= pd.Timedelta(days=10)]
    m["dist"] = (m["x_psx"] - m["ex_date"]).abs()
    m = m.sort_values("dist").drop_duplicates(["symbol", "ex_date"]).drop(columns="dist")
    s = _sessions(f)
    pos = pd.Series(np.arange(len(s)), index=s)
    m["x_idx"] = m["x_psx"].map(pos)
    m["ann_session"] = snap_to_session(m["announce_date"], s, 0)
    m["ann_idx"] = m["ann_session"].map(pos)
    return m.dropna(subset=["x_idx"]).reset_index(drop=True)


def results_meetings(f: pd.DataFrame, e: pd.DataFrame) -> pd.DataFrame:
    """Board meetings that produced a results filing within 3 days, with the
    notice date (PSX gives ~7 days' notice) — known in advance, so tradeable."""
    a = store.read_parquet(store.path("seed", "akd", "announcements.parquet"))
    bm = a[a["announcementType"].str.startswith("BMV1", na=False) & a["heldDate"].notna()]
    bm = bm[["symbol", "date", "heldDate"]].rename(columns={"date": "notice_date"})
    bm = bm[(bm["heldDate"] - bm["notice_date"]).dt.days.between(1, 30)]
    m = bm.merge(e[["symbol", "ann_date", "surprise", "eps_delta"]], on="symbol")
    m = m[(m["ann_date"] - m["heldDate"]).dt.days.between(0, 3)]
    m = m.sort_values("ann_date").drop_duplicates(["symbol", "heldDate"])
    s = _sessions(f)
    pos = pd.Series(np.arange(len(s)), index=s)
    m["x_idx"] = snap_to_session(m["heldDate"], s, 0).map(pos)
    m["notice_idx"] = snap_to_session(m["notice_date"], s, 0).map(pos)
    # the previous results' surprise, as known before this meeting
    prev = e[["symbol", "d0", "eps_delta"]].rename(columns={"d0": "prev_d0", "eps_delta": "prev_delta"})
    prev["prev_d0"] = prev["prev_d0"].astype("datetime64[ns]")
    m["heldDate"] = m["heldDate"].astype("datetime64[ns]")
    m = pd.merge_asof(m.sort_values("heldDate"), prev.sort_values("prev_d0"),
                      left_on="heldDate", right_on="prev_d0", by="symbol",
                      direction="backward", allow_exact_matches=False)
    return m.dropna(subset=["x_idx", "notice_idx"]).reset_index(drop=True)


def unusual_movement(f: pd.DataFrame) -> pd.DataFrame:
    a = store.read_parquet(store.path("seed", "akd", "announcements.parquet"))
    fam = a["announcementType"].str[:4]
    um = a[fam.isin(["MISV", "MIV1"]) & a["title"].str.contains("unusual", case=False, na=False)]
    um = um[["symbol", "date"]].drop_duplicates().rename(columns={"date": "ann_date"})
    um["d0"] = snap_to_session(um["ann_date"], _sessions(f), 0)
    return um.dropna(subset=["d0"])


def pit_fundamentals(f: pd.DataFrame, e: pd.DataFrame) -> pd.DataFrame:
    """For every symbol-day: the latest results known at that close (as-of d0).
    Adds last_eps_annual, last_q_delta, last_q_sales_g, last_oneoff, days_since_results."""
    e = e.sort_values("d0")
    ann = e[e["annual"]][["symbol", "d0", "eps"]].rename(columns={"eps": "last_eps_annual",
                                                                  "d0": "d_annual"})
    allr = e[["symbol", "d0", "eps_delta", "sales_g", "oneoff_flag", "eps"]].rename(
        columns={"d0": "d_last", "eps_delta": "last_eps_delta", "sales_g": "last_sales_g",
                 "oneoff_flag": "last_oneoff", "eps": "last_eps"})
    ns = "datetime64[ns]"                 # merge_asof needs identical datetime resolution
    ann["d_annual"] = ann["d_annual"].astype(ns)
    allr["d_last"] = allr["d_last"].astype(ns)
    base = f[["symbol", "date"]].sort_values("date").reset_index()
    base["date"] = base["date"].astype(ns)
    base = pd.merge_asof(base, ann.sort_values("d_annual"), left_on="date", right_on="d_annual",
                         by="symbol", direction="backward")
    base = pd.merge_asof(base.sort_values("date"), allr.sort_values("d_last"), left_on="date",
                         right_on="d_last", by="symbol", direction="backward")
    base["days_since_results"] = (base["date"] - base["d_last"]).dt.days
    return base.set_index("index").sort_index().drop(columns=["symbol", "date"])
