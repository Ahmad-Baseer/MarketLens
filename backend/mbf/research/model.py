"""Composite score: combine many small, independent edges into one ranking.

Single factors (reversal, fundamentals, pre-results, dividend run-up, ...) each
add a little; none clears costs alone except the dividend run-up. A linear
model over point-in-time features ranks every universe stock every day by its
expected 5-day return in EXCESS of the day's average stock. Linear on purpose:
each pick's score decomposes into named contributions, which is the "why" shown
on a signal's page.

Validation is walk-forward: year Y is scored by a model fitted only on years
before Y (with a purge gap so no training outcome overlaps Y).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from mbf.research import events as ev

log = logging.getLogger(__name__)

TARGET_RULE = "C_time5_O"
TRAIN_FROM = pd.Timestamp("2018-01-01")      # event features (AKD) exist from 2018
PURGE_SESSIONS = 7
ALPHA = 50.0                                  # ridge penalty on standardised features


def _expand(events: pd.DataFrame, start_col: str, end_col: str, s: pd.DatetimeIndex,
            keep: list[str]) -> pd.DataFrame:
    """One row per (symbol, session idx) inside each event's [start, end] window."""
    e = events.dropna(subset=[start_col, end_col]).copy()
    e = e[e[end_col] >= e[start_col]]
    n = (e[end_col] - e[start_col] + 1).astype(int)
    rep = e.loc[e.index.repeat(n)].copy()
    rep["idx"] = (rep[start_col].astype(int)
                  + rep.groupby(level=0).cumcount().to_numpy())
    rep = rep[(rep["idx"] >= 0) & (rep["idx"] < len(s))]
    rep["date"] = s[rep["idx"].to_numpy()]
    return rep[["symbol", "date", "idx"] + keep]


def event_features(f: pd.DataFrame) -> pd.DataFrame:
    """Per symbol-day event context, all known at that day's close."""
    s = ev._sessions(f)
    pos = pd.Series(np.arange(len(s)), index=s)
    E = ev.earnings(f)
    out = f[["symbol", "date"]].copy()

    def attach(df, cols, agg="first"):
        nonlocal out
        df = df.groupby(["symbol", "date"])[cols].agg(agg).reset_index()
        out = out.merge(df, on=["symbol", "date"], how="left")

    # upcoming results meeting (notice already published)
    R = ev.results_meetings(f, E)
    R["end"] = R["x_idx"] - 1
    r = _expand(R, "notice_idx", "end", s, ["x_idx", "prev_delta"])
    r["dtr"] = r["x_idx"] - r["idx"]
    attach(r, ["dtr", "prev_delta"], "min")
    # upcoming ex-date of an announced payout
    P = ev.payouts(f)
    P["end"] = P["x_idx"] - 1
    p = _expand(P, "ann_idx", "end", s, ["x_idx", "div_rs", "bonus_r"])
    p["dte"] = p["x_idx"] - p["idx"]
    attach(p, ["dte", "div_rs", "bonus_r"], "min")
    # days since the latest results, with its surprise
    E["d0_idx"] = E["d0"].map(pos)
    E["end"] = E["d0_idx"] + 5
    q = _expand(E, "d0_idx", "end", s, ["d0_idx", "surprise"])
    q["since_res"] = q["idx"] - q["d0_idx"]
    attach(q.sort_values("since_res"), ["since_res", "surprise"], "first")
    # PSX unusual-movement letter in the last 20 sessions
    U = ev.unusual_movement(f)
    U["d0_idx"] = U["d0"].map(pos)
    U["end"] = U["d0_idx"] + 20
    u = _expand(U, "d0_idx", "end", s, [])
    u["unusual"] = True
    attach(u, ["unusual"], "max")
    return out.drop(columns=["symbol", "date"]).set_axis(f.index)


def _xs(f, col):
    u = f["in_universe"]
    r = pd.Series(np.nan, index=f.index)
    r[u] = f.loc[u].groupby("date")[col].rank(pct=True)
    return r


def features(f: pd.DataFrame) -> pd.DataFrame:
    """Model inputs (all as of the close). Missing event context = 0."""
    E = ev.earnings(f)
    pit = ev.pit_fundamentals(f, E)
    evf = event_features(f)
    yld = (evf["div_rs"] / f["close"]).where(evf["dte"].between(1, 10)).fillna(0).clip(0, 0.15)
    X = pd.DataFrame({
        "reversal_5d": 1 - _xs(f, "r5"),
        "momentum_20d": _xs(f, "r20"),
        "rsi2_low": 1 - f["rsi2"] / 100,
        "above_200dma": (f["dma200"] > 0).astype(float),
        "ma50_rising": f["ma50_rising"].astype(float),
        "volume_spike": np.clip(np.log1p(f["vol_ratio"].fillna(1)), 0, 3),
        "drawdown_120d": -f["off_hi120"].clip(-0.9, 0),
        "close_near_high": f["close_loc"].fillna(0.5),
        "volatility": _xs(f, "atr_pct"),
        "liquidity": -np.log(f["to_rank"].clip(1, 300)),
        "profitable": (pit["last_eps_annual"] > 0).astype(float),
        "eps_growing": (pit["last_eps_delta"] > 0).astype(float),
        "oneoff_profit": pit["last_oneoff"].fillna(False).astype(float),
        "results_in_1_5d": evf["dtr"].between(1, 5).astype(float),
        "results_soon_after_beat": (evf["dtr"].between(1, 5) & (evf["prev_delta"] > 0)).astype(float),
        "dividend_yield_upcoming": yld,
        "exdate_in_2_8d": (evf["dte"].between(2, 8) & (yld >= 0.02)).astype(float),
        "just_beat": ((evf["since_res"] <= 3) & (evf["surprise"] > 0)).astype(float),
        "just_missed": ((evf["since_res"] <= 3) & (evf["surprise"] < 0)).astype(float),
        "unusual_letter_20d": evf["unusual"].fillna(False).astype(float),
        "market_trend": f["mkt_dma200"].clip(-0.3, 0.3).fillna(0),
        "market_breadth": f["breadth50"].fillna(0.5),
        "market_5d": f["mkt_r5"].clip(-0.15, 0.15).fillna(0),
    }, index=f.index)
    return X.fillna(0.0)


def _fit(X: np.ndarray, y: np.ndarray, alpha: float = ALPHA):
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    Z = (X - mu) / sd
    A = Z.T @ Z + alpha * np.eye(Z.shape[1])
    b = np.linalg.solve(A, Z.T @ (y - y.mean()))
    return mu, sd, b, y.mean()


def _predict(model, X):
    mu, sd, b, c = model
    return ((X - mu) / sd) @ b + c


def walk_forward(f: pd.DataFrame, out: pd.DataFrame, X: pd.DataFrame,
                 first_year: int = 2019, rule: str = TARGET_RULE) -> tuple[pd.Series, dict]:
    """Out-of-sample score for every universe row from first_year on."""
    ok = f["in_universe"] & out[f"{rule}__entered"]
    net = out[f"{rule}__net"]
    excess = net - net[ok].groupby(f.loc[ok, "date"]).transform("mean")
    sessions = pd.DatetimeIndex(np.sort(f["date"].unique()))
    score = pd.Series(np.nan, index=f.index)
    models = {}
    for y in range(first_year, f["date"].dt.year.max() + 1):
        start = pd.Timestamp(f"{y}-01-01")
        cut = sessions[max(0, sessions.searchsorted(start) - PURGE_SESSIONS)]
        tr = ok & (f["date"] >= TRAIN_FROM) & (f["date"] < cut) & excess.notna()
        te = f["in_universe"] & (f["date"] >= start) & (f["date"] < pd.Timestamp(f"{y + 1}-01-01"))
        if tr.sum() < 5000 or te.sum() == 0:
            continue
        m = _fit(X[tr].to_numpy(float), excess[tr].clip(-0.3, 0.3).to_numpy(float))
        score[te] = _predict(m, X[te].to_numpy(float))
        models[y] = m
        log.info("walk-forward %d: trained on %s rows (< %s), scored %s", y, f"{int(tr.sum()):,}",
                 cut.date(), f"{int(te.sum()):,}")
    return score, models


def coefficients(model, names) -> pd.Series:
    mu, sd, b, c = model
    return pd.Series(b, index=names).sort_values()


def top_k(f: pd.DataFrame, score: pd.Series, k: int = 3, min_score: float = 0.0) -> pd.Series:
    """Daily picks: the k highest scores per date, only if above min_score."""
    s = score.where(f["in_universe"] & (score > min_score))
    rank = s.groupby(f["date"]).rank(ascending=False, method="first")
    return (rank <= k).fillna(False)
