"""Per symbol-day features, using only information available at that day's close.

Computed on the modern era only (see config.MODERN_FROM): older rows have no
real opens and unadjusted ex-dates, which would poison every indicator.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from mbf import config, store

log = logging.getLogger(__name__)

UNIVERSE_TOP_N = 200           # most-traded names by 20-day median turnover
MIN_TURNOVER = 2_000_000       # Rs/day, floor on top of the rank
MIN_PRICE = 5.0
MIN_ATR = 0.005                # below this the price has barely moved for weeks: no usable levels
LOCK_MOVE = 0.049              # high == low and |move| >= this: circuit-locked day


def _roll(g, col, n, fn="mean", minp=None):
    return g[col].transform(lambda s: getattr(s.rolling(n, min_periods=minp or n), fn)())


def _rsi(g, col, n):
    def f(s):
        d = s.diff()
        up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        return 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return g[col].transform(f)


def compute(daily: pd.DataFrame | None = None) -> pd.DataFrame:
    d = daily if daily is not None else store.read_parquet(store.path("prices", "daily.parquet"))
    d = d[d["modern"]].sort_values(["symbol", "date"]).reset_index(drop=True)
    g = d.groupby("symbol", sort=False)

    # adjusted OHLC; opens are real in the modern era
    pc = g["adj_close"].shift(1)
    tr = np.maximum(d["adj_high"] - d["adj_low"],
                    np.maximum((d["adj_high"] - pc).abs(), (d["adj_low"] - pc).abs()))
    d["tr"] = tr.fillna(d["adj_high"] - d["adj_low"])
    d["atr_pct"] = _roll(d.groupby("symbol", sort=False), "tr", 14) / d["adj_close"]

    d["med_to20"] = _roll(g, "turnover", 20, "median", 15)
    d["avg_to20_prev"] = g["turnover"].transform(lambda s: s.shift(1).rolling(20, min_periods=15).mean())
    d["vol_ratio"] = d["turnover"] / d["avg_to20_prev"]

    for n in (1, 3, 5, 20, 60, 120):
        d[f"r{n}"] = d["adj_close"] / g["adj_close"].shift(n) - 1
    for n in (5, 20, 50, 200):
        d[f"dma{n}"] = d["adj_close"] / _roll(g, "adj_close", n, "mean", int(n * 0.9)) - 1
    ma50 = _roll(g, "adj_close", 50, "mean", 45)
    d["ma50_rising"] = ma50 > ma50.groupby(d["symbol"], sort=False).shift(10)
    d["hi20_prev"] = g["adj_high"].transform(lambda s: s.shift(1).rolling(20, min_periods=18).max())
    d["lo20_prev"] = g["adj_low"].transform(lambda s: s.shift(1).rolling(20, min_periods=18).min())
    d["off_hi120"] = d["adj_close"] / _roll(g, "adj_high", 120, "max", 100) - 1
    d["off_hi250"] = d["adj_close"] / _roll(g, "adj_high", 250, "max", 200) - 1
    rng = (d["adj_high"] - d["adj_low"]) / d["adj_close"]
    d["rng"] = rng
    g = d.groupby("symbol", sort=False)
    d["rng10_vs60"] = _roll(g, "rng", 10) / _roll(g, "rng", 60, "mean", 50)
    d["close_loc"] = ((d["adj_close"] - d["adj_low"]) / (d["adj_high"] - d["adj_low"])).where(
        d["adj_high"] > d["adj_low"])
    d["rsi2"] = _rsi(g, "adj_close", 2)
    d["rsi14"] = _rsi(g, "adj_close", 14)
    d["suspect20"] = g["suspect"].transform(lambda s: s.astype(float).rolling(20, min_periods=1).max()) > 0

    raw_move = d["close"] / d["ldcp"].where(d["ldcp"] > 0) - 1
    flat = d["high"] == d["low"]
    d["locked_up"] = d["traded"] & flat & (raw_move >= LOCK_MOVE)
    d["locked_dn"] = d["traded"] & flat & (raw_move <= -LOCK_MOVE)

    # universe as of the close: liquid, priced, clean
    d["to_rank"] = d.groupby("date")["med_to20"].rank(ascending=False, method="first")
    d["in_universe"] = (d["traded"] & (d["close"] >= MIN_PRICE) & (d["to_rank"] <= UNIVERSE_TOP_N)
                        & (d["med_to20"] >= MIN_TURNOVER) & ~d["suspect20"] & (d["atr_pct"] >= MIN_ATR))

    # market context: cap-weighted proxy + breadth of the universe
    px = store.read_parquet(store.path("indices", "market_proxy.parquet"))
    if not px.empty:
        m = px[["date", "level_cw", "ret_cw"]].sort_values("date").copy()
        m["mkt_dma50"] = m["level_cw"] / m["level_cw"].rolling(50).mean() - 1
        m["mkt_dma200"] = m["level_cw"] / m["level_cw"].rolling(200).mean() - 1
        m["mkt_r5"] = m["level_cw"] / m["level_cw"].shift(5) - 1
        m["mkt_r20"] = m["level_cw"] / m["level_cw"].shift(20) - 1
        d = d.merge(m[["date", "ret_cw", "mkt_dma50", "mkt_dma200", "mkt_r5", "mkt_r20"]], on="date", how="left")
    u = d[d["in_universe"]]
    breadth = (u["dma50"] > 0).groupby(u["date"]).mean().rename("breadth50")
    d = d.merge(breadth, left_on="date", right_index=True, how="left")
    d = d.drop(columns=["tr", "rng", "avg_to20_prev"])
    log.info("features: %s rows, %s in universe, %s..%s", f"{len(d):,}",
             f"{int(d['in_universe'].sum()):,}", d["date"].min().date(), d["date"].max().date())
    return d


def build() -> pd.DataFrame:
    f = compute()
    store.write_parquet(f, store.path("research", "features.parquet"))
    return f
