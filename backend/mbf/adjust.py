"""Corporate-action adjustment from PSX's own LDCP field.

On an ex-date PSX sets LDCP (last day's closing price) to the *adjusted*
previous close: OGDC closed 315.91 on 2026-10-07 and went ex a Rs 6 dividend,
so LDCP on 2026-10-08 is 309.91. The ratio

    f_t = LDCP_t / close_{t-1}

is therefore the exact adjustment factor for every dividend, bonus and rights
issue, with nothing else needed. Two consequences used throughout:

* daily total return      r_t = close_t / LDCP_t - 1
* back-adjusted prices    P_adj(t) = P(t) * prod_{s > t} f_s

The raw (unadjusted) series is kept alongside: it is what a chart shows and
what stops/targets are quoted in.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from mbf import config, store

log = logging.getLogger(__name__)

TICK = 0.01                 # PSX price tick; smaller LDCP gaps are rounding
F_MIN, F_MAX = 0.02, 50.0   # outside this a "factor" is a data error, not an event
MAX_GAP_DAYS = 30           # symbol absent longer than this: a resumption, not an ex-date


# PSX's daily table labels some bonds 'equity' (e.g. GoP Ijara Sukuk
# P01GIS031225 traded Rs 1.3 trillion face value in one day in 2025), so debt
# is also recognised by name: government securities, T-bills, TFCs, sukuks.
DEBT_RE = r"^P\d{2}[A-Z]{2,5}\d{4,6}$|^PK\d{2}TB\d{6}$|TFC|SUK"


def is_future(symbol: pd.Series) -> pd.Series:
    """Deliverable futures carry a month suffix: MCB-OCT, MCB-OCTB, NPL-NOV."""
    return symbol.str.contains("-", regex=False)


def non_equity_symbols() -> set[str]:
    """Current debt list + index codes, from the reference data."""
    out = set(config.INDICES)
    sym = store.read_parquet(store.path("ref", "symbols.parquet"))
    if not sym.empty:
        out |= set(sym.loc[sym["is_debt"].astype(bool), "symbol"])
    mw = store.read_parquet(store.path("ref", "market_watch.parquet"))
    if not mw.empty:
        out |= {c for s in mw["listed_in"].dropna() for c in s.split(",") if c}
    return out


def equities(raw: pd.DataFrame, exclude: set[str] | None = None) -> pd.DataFrame:
    s = raw["symbol"]
    excl = {x.upper() for x in (exclude or set())}        # 'BKTi' vs 'BKTI'
    m = ((raw["row_type"] == "equity") & ~is_future(s)
         & ~s.str.contains(DEBT_RE, regex=True) & ~s.str.upper().isin(excl))
    return raw.loc[m].copy()


def adjust(raw: pd.DataFrame, exclude: set[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """raw daily rows -> (adjusted daily frame, corporate-action events)."""
    df = equities(raw, exclude)
    df = df[df["close"] > 0].sort_values(["symbol", "date"]).reset_index(drop=True)

    # before MODERN_FROM there are no real opens and LDCP is not adjusted (see config)
    df["modern"] = df["date"] >= pd.Timestamp(config.MODERN_FROM)
    df.loc[~df["modern"], "open"] = np.nan

    # untraded days are listed with O/H/L = 0 and close = LDCP
    df["traded"] = df["volume"].fillna(0) > 0
    for c in ("open", "high", "low"):
        bad = ~df["traded"] | (df[c] <= 0)
        df.loc[bad, c] = df.loc[bad, "close"]
    lo = df[["open", "high", "low", "close"]].min(axis=1)
    hi = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"], df["high"] = lo, hi
    df["turnover"] = df["close"] * df["volume"].fillna(0)

    g = df.groupby("symbol", sort=False)
    df["prev_close"] = g["close"].shift(1)
    df["prev_date"] = g["date"].shift(1)

    gap = df["ldcp"] - df["prev_close"]
    # pre-modern LDCP gaps are noise, not corporate actions: never candidates
    candidate = (df["modern"] & (df["prev_close"] > 0) & (df["ldcp"] > 0)
                 & (gap.abs() >= TICK - 1e-9))
    f = (df["ldcp"] / df["prev_close"]).where(candidate)
    plausible = f.between(F_MIN, F_MAX)                 # False where there is no event
    implausible = candidate & ~plausible
    long_gap = (df["date"] - df["prev_date"]).dt.days > MAX_GAP_DAYS
    after_gap = candidate & long_gap
    applied = plausible & ~after_gap
    df["factor"] = f.where(applied, 1.0).fillna(1.0)

    events = df.loc[candidate, ["symbol", "date", "prev_date", "prev_close", "ldcp"]].copy()
    events["factor"] = f[candidate]
    events["implied_cash"] = events["prev_close"] - events["ldcp"]
    events["applied"] = applied[candidate]
    events["kind_guess"] = np.select(
        [implausible[candidate], after_gap[candidate], events["factor"] > 1.0,
         events["factor"] < 0.5],
        ["implausible", "after_gap", "up_adjustment", "large_split_or_bonus"],
        "dividend_bonus_or_rights")

    # back-adjust: multiply everything before each event by its factor
    nxt = df.groupby("symbol", sort=False)["factor"].shift(-1).fillna(1.0)
    df["adj_mult"] = (nxt.iloc[::-1].groupby(df["symbol"].iloc[::-1], sort=False).cumprod()
                      .iloc[::-1])
    for c in ("open", "high", "low", "close"):
        df[f"adj_{c}"] = df[c] * df["adj_mult"]

    # daily total return: PSX's own reference price where it is usable ...
    ref = df["ldcp"].where(df["modern"] & (df["ldcp"] > 0) & ~implausible)
    df["ret"] = df["close"] / ref - 1.0
    # ... else the previous close, but only across a short gap: after a long
    # suspension the "daily" return would really be months of unknown moves
    alt = df["adj_close"] / df.groupby("symbol", sort=False)["adj_close"].shift(1) - 1.0
    use_alt = df["ret"].isna() & ~long_gap & df["prev_close"].gt(0)
    df.loc[use_alt, "ret"] = alt[use_alt]

    # beyond any circuit breaker PSX has used (now +/-10% or Rs 1): flag, don't trust
    base = ref.fillna(df["prev_close"])
    df["suspect"] = df["ret"].abs() > np.maximum(0.30, 1.5 / base.where(base > 0))

    cols = ["date", "symbol", "open", "high", "low", "close", "volume", "ldcp", "traded",
            "turnover", "factor", "adj_mult", "adj_open", "adj_high", "adj_low", "adj_close", "ret",
            "suspect", "modern"]
    return df[cols], events.reset_index(drop=True)


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = store.read_parquet(store.path("prices", "daily_raw.parquet"))
    if raw.empty:
        raise FileNotFoundError("prices/daily_raw.parquet missing — run backfill/compact first")
    daily, events = adjust(raw, non_equity_symbols())
    store.write_parquet(daily, store.path("prices", "daily.parquet"))
    store.write_parquet(events, store.path("prices", "corporate_actions.parquet"))
    skipped = events.loc[~events["applied"], "kind_guess"].value_counts().to_dict()
    log.info("adjust: %s rows, %d symbols, %d corporate-action events applied; not applied: %s",
             f"{len(daily):,}", daily["symbol"].nunique(), int(events["applied"].sum()), skipped)
    return daily, events
