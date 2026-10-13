"""Market proxy index for the years PSX's own index series doesn't cover.

PSX serves only ~5 years of KSE-100 levels, but signals need a benchmark and a
market-regime input back to 2000. We rebuild one from the stock data, using
only information known before each day starts (no look-ahead):

* ret_cw  — free-float market-cap weighted, top 100 by estimated cap. This is
            how KSE-100 itself is built. Historical cap is estimated as today's
            free-float shares x the back-adjusted price, which carries share
            counts correctly through bonus issues and splits but not through
            new issuance; companies delisted before today have no share count
            and drop out (coverage is reported).
* ret_ew  — equal weight across the 100 most-traded names: "the average
            liquid stock", the right baseline for judging a stock-picking signal.

Where KSE-100 exists the proxies are compared with it in the quality report.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from mbf import config, store

log = logging.getLogger(__name__)

TOP_N = 100
LOOKBACK = 20
RET_CLIP = 0.5          # a +/-50% day in a top-100 name is almost surely a data error


def _shares_now() -> pd.Series:
    snaps = sorted((config.DATA_DIR / "fundamentals" / "snapshots").glob("*"))
    if not snaps:
        return pd.Series(dtype=float)
    eq = pd.read_parquet(snaps[-1] / "equity.parquet")
    ff = eq["free_float_shares"].where(eq["free_float_shares"] > 0, eq["shares"])
    return pd.Series(ff.values, index=eq["symbol"]).dropna()


def build(daily: pd.DataFrame | None = None, top_n: int = TOP_N) -> pd.DataFrame:
    d = daily if daily is not None else store.read_parquet(store.path("prices", "daily.parquet"))
    d = d[["symbol", "date", "ret", "turnover", "adj_close"]].sort_values(["symbol", "date"]).copy()
    g = d.groupby("symbol", sort=False)
    # everything used for selection/weights is as of yesterday's close
    d["liq"] = g["turnover"].transform(lambda s: s.shift(1).rolling(LOOKBACK, min_periods=10).median())
    d["cap"] = g["adj_close"].shift(1) * d["symbol"].map(_shares_now())
    d = d.dropna(subset=["ret"])
    d["r"] = d["ret"].clip(-RET_CLIP, RET_CLIP)

    # equal weight, most traded
    lq = d[d["liq"] > 0].copy()
    lq = lq[lq.groupby("date")["liq"].rank(ascending=False, method="first") <= top_n]
    ew = lq.groupby("date")["r"].mean().rename("ret_ew")

    # cap weight, largest (must also trade: liq > 0)
    cp = d[(d["cap"] > 0) & (d["liq"] > 0)].copy()
    cp = cp[cp.groupby("date")["cap"].rank(ascending=False, method="first") <= top_n]
    cp["w"] = cp["cap"] / cp.groupby("date")["cap"].transform("sum")
    cw = (cp["r"] * cp["w"]).groupby(cp["date"]).sum().rename("ret_cw")

    # coverage: share of the day's traded value in names that have a share count
    tv = d.groupby("date")["turnover"].sum()
    tv_cov = d[d["cap"] > 0].groupby("date")["turnover"].sum()
    px = pd.concat([cw, ew, (tv_cov / tv).rename("cw_coverage"),
                    cp.groupby("date").size().rename("cw_names")], axis=1).sort_index()
    for c in ("cw", "ew"):
        px[f"level_{c}"] = 1000 * (1 + px[f"ret_{c}"].fillna(0)).cumprod()
    px = px.reset_index(names="date")
    store.write_parquet(px, store.path("indices", "market_proxy.parquet"))
    log.info("market proxy: %d days, %s..%s", len(px), px["date"].min().date(), px["date"].max().date())
    return px


def compare_with_kse100(px: pd.DataFrame) -> dict:
    idx = store.read_parquet(store.path("indices", "eod.parquet"))
    if idx.empty:
        return {}
    k = idx[idx["symbol"] == "KSE100"].sort_values("date")
    k = k.assign(ret_kse=k["close"].pct_change())[["date", "ret_kse"]]
    m = px.merge(k, on="date").dropna(subset=["ret_kse", "ret_cw", "ret_ew"])
    out = {"days": len(m), "cum_kse": float((1 + m["ret_kse"]).prod() - 1)}
    for c in ("ret_cw", "ret_ew"):
        out[f"corr_{c}"] = float(m[c].corr(m["ret_kse"]))
        out[f"beta_{c}"] = float(np.cov(m[c], m["ret_kse"])[0, 1] / m["ret_kse"].var())
        out[f"cum_{c}"] = float((1 + m[c]).prod() - 1)
    return out
