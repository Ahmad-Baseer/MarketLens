"""Par (face) value per share, needed because PSX announces cash dividends as a
percentage of par ("30% (D)" = Rs 3 on a Rs 10 share).

Evidence, best first:
  1. PSX's own ex-date adjustments: on the ex-date LDCP = previous close minus the
     dividend, so implied cash / (pct / 100) = par. Snapped to the usual face values.
  2. The AKD company profiles (static snapshot, 2026).
  3. Rs 10, the face value of most PSX shares.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from mbf import config, store

log = logging.getLogger(__name__)

STANDARD = np.array([1, 2, 2.5, 3.5, 5, 10, 25, 50, 100], dtype=float)
DEFAULT_PAR = 10.0


def _snap(x: float, tol: float = 0.08) -> float:
    if not np.isfinite(x) or x <= 0:
        return np.nan
    i = np.argmin(np.abs(STANDARD / x - 1))
    return STANDARD[i] if abs(STANDARD[i] / x - 1) <= tol else np.nan


def ex_date_for(bc_from: pd.Timestamp, sessions: pd.DatetimeIndex) -> pd.Timestamp | None:
    """PSX ex-date = book-closure start minus 1 session (T+1, from 2026-02-09), minus 2 before."""
    i = sessions.searchsorted(bc_from)            # first session on/after book closure start
    if i >= len(sessions):
        return None                                # beyond the calendar we know
    lag = 1 if bc_from >= pd.Timestamp(config.T1_SETTLEMENT_FROM) else 2
    j = i - lag
    return sessions[j] if 0 <= j < len(sessions) else None


def observations(sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per PSX cash-only payout whose ex-date adjustment we can see."""
    p = store.read_parquet(store.path("events", "payouts.parquet"))
    p = p.dropna(subset=["book_closure_from"])
    comp = p.groupby(["symbol", "announced_at"])["kind"].agg(lambda k: set(k.dropna()))
    cash_only = comp[comp.apply(lambda k: k == {"dividend"})].index
    p = p.set_index(["symbol", "announced_at"]).loc[lambda d: d.index.isin(cash_only)].reset_index()
    p = p[p["pct"].notna() & (p["pct"] > 0)]
    ca = store.read_parquet(store.path("prices", "corporate_actions.parquet"))
    ca = ca[ca["applied"] & (ca["implied_cash"] > 0)]
    rows = []
    for r in p.itertuples():
        x = ex_date_for(r.book_closure_from, sessions)
        if x is None:
            continue
        c = ca[(ca["symbol"] == r.symbol) & ((ca["date"] - x).abs() <= pd.Timedelta(days=4))]
        if len(c) != 1:
            continue
        cash = float(c["implied_cash"].iloc[0])
        rows.append({"symbol": r.symbol, "ex_date": c["date"].iloc[0], "pct": r.pct, "cash": cash,
                     "par_raw": cash / (r.pct / 100), "par": _snap(cash / (r.pct / 100))})
    return pd.DataFrame(rows)


def build(sessions: pd.DatetimeIndex) -> pd.DataFrame:
    obs = observations(sessions)
    akd = store.read_parquet(store.path("seed", "akd", "profiles.parquet"))
    # AKD codes an unknown par as 0
    akd = akd[akd["par_value"] > 0][["symbol", "par_value"]].rename(columns={"par_value": "par_akd"}) if not akd.empty \
        else pd.DataFrame(columns=["symbol", "par_akd"])
    if obs.empty:
        psx = pd.DataFrame(columns=["symbol", "par_psx", "n_obs", "n_agree"])
    else:
        o = obs.dropna(subset=["par"])
        psx = (o.sort_values("ex_date").groupby("symbol")
                .agg(par_psx=("par", lambda s: s.iloc[-3:].mode().iloc[-1]),   # recent majority
                     n_obs=("par", "size"),
                     n_agree=("par", lambda s: int((s == s.iloc[-3:].mode().iloc[-1]).sum())))
                .reset_index())
    out = psx.merge(akd, on="symbol", how="outer")
    out["par"] = out["par_psx"].fillna(out["par_akd"]).fillna(DEFAULT_PAR)
    out["source"] = np.where(out["par_psx"].notna(), "psx_exdate",
                             np.where(out["par_akd"].notna(), "akd", "default"))
    store.write_parquet(out, store.path("ref", "par_values.parquet"))
    dis = out[out["par_psx"].notna() & out["par_akd"].notna() & (out["par_psx"] != out["par_akd"])]
    log.info("par values: %d symbols (%d from PSX ex-dates, %d disagree with AKD)",
             len(out), int(out["par_psx"].notna().sum()), len(dis))
    return out


def lookup(symbols) -> pd.Series:
    t = store.read_parquet(store.path("ref", "par_values.parquet"))
    m = t.set_index("symbol")["par"] if not t.empty else pd.Series(dtype=float)
    return pd.Series([m.get(s, DEFAULT_PAR) for s in symbols], index=list(symbols), dtype=float)
