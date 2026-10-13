#!/usr/bin/env python3
"""
=============================================================================
 Multi Beggar Finder — refresh.py       ONE FILE. ONE COMMAND.
=============================================================================

    python refresh.py

Reads the mbf_*.csv files exported by AKD_PULL.js, and writes:

    screen_today.csv     the ranked list, one row per tradeable symbol
    mbf_screen.html      the dashboard (open it in any browser)

Everything happens in one pass, in memory. Only pandas and numpy are required.
If pyarrow is also installed it additionally writes *.parquet files, which the
research scripts (panel.py / baserate.py / sweep.py / signals.py / validate.py)
need — the screen itself does not.

    python refresh.py --check      validate the input CSVs and stop
    python refresh.py --dir PATH   look for the CSVs somewhere else
    python refresh.py --top 30     print more rows at the end

WHAT THIS FILE KNOWS THAT IS NOT OBVIOUS
----------------------------------------
1. AKD's price series is a TOTAL-RETURN series: dividends AND bonuses are
   already adjusted out. Measured over 2021-09..2026-06 —
       cash-dividend ex-dates (n=1611): actual -0.21%  vs mechanical -5.18%
       bonus ex-dates          (n= 161): actual -0.10%  vs mechanical -16.98%
   So we must NOT apply our own adjustment (that would double-count), and we
   de-adjust back to a price-only series for anything a chart would show.
2. One economic payout is often filed twice under different type codes. De-
   duplicating on the type code applies the factor twice (verified on AABS
   2023-09-21: implied k 0.9883 = 0.9941^2). Dedupe on (symbol, ex_date).
3. `value` in the price file is 100% zero — turnover must be close x volume.
4. roe / roa / npm / div_yield are stored as FRACTIONS (median roe 0.0811);
   ltde / cur_ratio / pe_ratio / pb_ratio are plain ratios.
5. Never compute P/E as (today's price) / (their per-share EPS). When the share
   count changes those refer to different shares and you get nonsense — the
   first build ranked DLL top on "P/E 0.17, P/B 0.07, EPS Rs 288 on a Rs 54
   share" because it had a 13.3x split AKD does not adjust for. Use AKD's own
   ratio (internally consistent) and re-price it, then gate for plausibility.
=============================================================================
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------- dependencies
try:
    import numpy as np
    import pandas as pd
except ImportError:                                     # pragma: no cover
    sys.exit("Missing dependencies. Run:\n"
             "    pip install pandas numpy pyarrow")

try:
    import pyarrow  # noqa: F401
    HAVE_PARQUET = True
except ImportError:
    HAVE_PARQUET = False

# --------------------------------------------------------------------- config
REQUIRED = ["mbf_prices.csv", "mbf_announcements.csv"]
OPTIONAL = ["mbf_fundamentals.csv", "mbf_profiles.csv", "mbf_statements.csv",
            "mbf_universe.csv"]

JUNK_SYMBOLS = {"AAL", "EXCHANGE", "HUSS", "NAZC", "OPENFUND", "OTHER",
                "SGABL", "PSX"}
MONTH_FIX = {"Dec": "December", "Decemeber": "December", "Jun": "June",
             "Sep": "September", "Sept": "September", "Mar": "March"}

MIN_TURNOVER = 300_000       # Rs, median daily over trailing 20 sessions
MIN_PRICE = 2.0
MIN_TRADED_FRAC = 0.70       # must have traded 70% of the last 60 sessions
MAX_STALE_DAYS = 5           # last print must be recent
MAX_FILING_AGE = 200         # days, else earnings info is treated as stale

PE_OK = (2.0, 60.0)          # plausibility windows; outside = unknown, NOT cheap
PB_OK = (0.10, 15.0)
EPS_YIELD_OK = (-0.40, 0.50)

K_STOP, K_TGT = 2.5, 3.0     # ATR20 multiples. Median PSX stock moves 4.19%/day,
                             # so a conventional 8% stop sits inside the noise
                             # and loses 0.95%/trade on random entries.
TICKET = 30_000

WEIGHTS = {"drawdown": 0.28,        # only component that survived holdout testing
           "earn_surprise": 0.20,
           "cheap_own_pb": 0.15,
           "earn_yield": 0.12,
           "cheap_sector": 0.10,
           "sales_growth": 0.08,
           "quality_roe": 0.07}


def log(msg=""):
    print(msg, flush=True)


def num(s):
    return pd.to_numeric(s, errors="coerce")


# =========================================================== STAGE 1: INGEST
def load_announcements(d: Path) -> pd.DataFrame:
    df = pd.read_csv(d / "mbf_announcements.csv", low_memory=False)
    for c in ("date", "periodEndDate", "previousPeriodEndDate", "exDate",
              "book_closure_date_from", "book_closure_date_to", "heldDate"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ("unconsolidatedSales", "unconsolidatedPat",
              "unconsolidatedQuarterEps", "unconsolidatedQuarterEpsYOY",
              "dividend", "bonus", "rightIssue", "rightPrice"):
        if c in df.columns:
            df[c] = num(df[c])
    df = df.dropna(subset=["symbol", "date"])
    df = df[~df["symbol"].isin(JUNK_SYMBOLS)]
    df["ann_family"] = df["announcementType"].astype(str).str[:4]
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def payout_events(ann: pd.DataFrame) -> pd.DataFrame:
    """Every ex-date at which AKD's adjustment factor steps.
    dividend/bonus/rightIssue are PERCENT OF PAR (Rs 10): dividend=13 -> Rs 1.30."""
    m = ann["exDate"].notna() & (
        (ann["dividend"].fillna(0) > 0) | (ann["bonus"].fillna(0) > 0)
        | (ann["rightIssue"].fillna(0) > 0))
    ev = ann.loc[m, ["symbol", "exDate", "date", "dividend", "bonus",
                     "rightIssue", "rightPrice", "announcementType"]].copy()
    ev = ev.rename(columns={"exDate": "ex_date", "date": "announce_date"})
    ev["div_rs"] = ev["dividend"].fillna(0) / 10.0
    ev["bonus_r"] = ev["bonus"].fillna(0) / 100.0
    ev["right_r"] = ev["rightIssue"].fillna(0) / 100.0
    ev["right_px"] = ev["rightPrice"]
    # ONE economic event per (symbol, ex_date) — see header note 2
    ev = (ev.sort_values(["symbol", "ex_date"])
            .groupby(["symbol", "ex_date"], as_index=False)
            .agg(div_rs=("div_rs", "max"), bonus_r=("bonus_r", "max"),
                 right_r=("right_r", "max"), right_px=("right_px", "max"),
                 announce_date=("announce_date", "min"),
                 n_filings=("announcementType", "size")))
    dup = int((ev["n_filings"] > 1).sum())
    if dup:
        log(f"    collapsed {dup} ex-dates filed more than once")
    return ev


def load_prices(d: Path) -> pd.DataFrame:
    df = pd.read_csv(d / "mbf_prices.csv")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = num(df[c])
    df = df.drop(columns=["value"], errors="ignore")     # always zero
    df = df[~df["symbol"].isin(JUNK_SYMBOLS)].dropna(subset=["date", "close"])

    n0 = len(df)
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    if n0 - len(df):
        log(f"    dropped {n0 - len(df):,} rows with non-positive prices")

    lo = df[["open", "high", "low", "close"]].min(axis=1)
    hi = df[["open", "high", "low", "close"]].max(axis=1)
    nv = int(((df["low"] > lo) | (df["high"] < hi)).sum())
    df["low"], df["high"] = lo, hi
    if nv:
        log(f"    clamped {nv:,} OHLC-inconsistent bars")

    df = (df.sort_values(["symbol", "date"])
            .drop_duplicates(["symbol", "date"], keep="last"))
    df["traded"] = (df["volume"].fillna(0) > 0).astype("int8")
    df["turnover"] = df["close"] * df["volume"].fillna(0)
    return df.reset_index(drop=True)


def deadjust(px: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Recover a price-only series from AKD's total-return series.

    A(t) = R(t) * f(t) where f steps at each ex-date and the newest segment
    has f = 1. For an event on cum price C:
        cash dividend D  ->  k = (C - D) / C
        bonus b          ->  k = 1 / (1 + b)
        rights r at P    ->  k = ((C + r*P) / (1 + r)) / C
    """
    px = px.sort_values(["symbol", "date"]).copy()
    px["deadj_f"] = 1.0
    ev = ev[(ev["div_rs"] > 0) | (ev["bonus_r"] > 0) | (ev["right_r"] > 0)]
    by = {s: g.sort_values("ex_date") for s, g in ev.groupby("symbol", sort=False)}

    out = []
    for sym, g in px.groupby("symbol", sort=False):
        g = g.sort_values("date").copy()
        evs = by.get(sym)
        if evs is None or evs.empty:
            out.append(g)
            continue
        ac = g.set_index("date")["close"]
        f = pd.Series(1.0, index=g.index)
        for _, e in evs.iloc[::-1].iterrows():          # newest -> oldest
            prior = ac[ac.index < e["ex_date"]]
            if prior.empty:
                continue
            C = float(prior.iloc[-1])
            if C <= 0:
                continue
            k = 1.0
            D = float(e["div_rs"] or 0)
            if 0 < D < C:
                k *= (C - D) / C
            b = float(e["bonus_r"] or 0)
            if b > 0:
                k *= 1.0 / (1.0 + b)
            r = float(e["right_r"] or 0)
            P = e["right_px"]
            if r > 0 and pd.notna(P):
                k *= ((C + r * float(P)) / (1.0 + r)) / C
            if 0 < k != 1.0:
                f.loc[g["date"] < e["ex_date"]] *= k
        g["deadj_f"] = f.values
        out.append(g)

    px = pd.concat(out).sort_values(["symbol", "date"])
    for c in ("open", "high", "low", "close"):
        px[f"tr_{c}"] = px[c]
        px[f"px_{c}"] = px[c] / px["deadj_f"]
    n = int((px["deadj_f"] != 1.0).sum())
    log(f"    de-adjusted {n:,} bars ({n / max(len(px), 1):.1%}) across "
        f"{px.loc[px['deadj_f'] != 1.0, 'symbol'].nunique()} symbols")
    return px.reset_index(drop=True)


def verify_deadjust(px: pd.DataFrame, ev: pd.DataFrame) -> bool:
    """Acceptance test: on the price-only series the mechanical dividend drop
    must reappear. If it does not, the de-adjustment is broken and every return
    downstream is wrong — so this is checked on every run, not assumed."""
    e = ev[(ev["div_rs"] > 0) & (ev["bonus_r"] == 0) & (ev["right_r"] == 0)]
    if e.empty:
        log("    (no clean dividend events to verify against)")
        return True
    e = e.tail(600)
    idx = px.set_index(["symbol", "date"])
    errs, n = [], 0
    for _, r in e.iterrows():
        g = px[px["symbol"] == r["symbol"]]
        if g.empty:
            continue
        a = g[g["date"] < r["ex_date"]].tail(1)
        b = g[g["date"] >= r["ex_date"]].head(1)
        if a.empty or b.empty:
            continue
        C = float(a["tr_close"].iloc[0])
        if C <= 0 or not (0 < r["div_rs"] < C):
            continue
        implied = float(a["deadj_f"].iloc[0]) / float(b["deadj_f"].iloc[0])
        expected = 1 - r["div_rs"] / C
        errs.append(abs(implied - expected))
        n += 1
    if n == 0:
        return True
    errs = np.array(errs)
    p99 = float(np.percentile(errs, 99))
    ok = p99 < 1e-4
    log(f"    de-adjust check on {n} dividend events: "
        f"99th-pct error {p99:.2e}  ->  {'OK' if ok else 'FAILED'}")
    if not ok:
        log("    WARNING: de-adjustment is not reproducing the mechanical drop. "
            "Treat price-only returns with suspicion.")
    return ok


def load_profiles(d: Path) -> pd.DataFrame:
    p = d / "mbf_profiles.csv"
    if not p.exists():
        return pd.DataFrame(columns=["symbol", "name", "sector_code",
                                     "sector_name", "active", "year_end",
                                     "par_value"])
    df = pd.read_csv(p)
    df = df[~df["symbol"].isin(JUNK_SYMBOLS)]
    df["year_end"] = df["year_end"].replace(MONTH_FIX)
    df["active"] = df["status"].map({1: True, 1.0: True, 0: False, 0.0: False})
    return df[["symbol", "name", "sector_code", "sector_name", "active",
               "year_end", "par_value"]].reset_index(drop=True)


# =========================================================== STAGE 2: FEATURES
def price_features(px: pd.DataFrame):
    asof = px["date"].max()
    rows = []
    for sym, g in px.groupby("symbol", sort=False):
        g = g.tail(300)
        if len(g) < 130:
            continue
        c = g["tr_close"].to_numpy(float)      # drawdown on the payout-free series
        p = g["px_close"].to_numpy(float)      # levels as the chart shows them
        h, l = g["px_high"].to_numpy(float), g["px_low"].to_numpy(float)
        v, tn = g["volume"].to_numpy(float), g["turnover"].to_numpy(float)
        td = g["traded"].to_numpy(float)
        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        v100 = np.nanmean(v[-100:])
        rows.append({
            "symbol": sym, "last_date": g["date"].iloc[-1], "price": p[-1],
            "atr_pct": np.nanmean(tr[-20:]) / p[-1] if p[-1] > 0 else np.nan,
            "turnover20": float(np.median(tn[-20:])),
            "traded_frac60": float(td[-60:].mean()),
            "mom20": c[-1] / c[-21] - 1 if len(c) > 21 else np.nan,
            "mom60": c[-1] / c[-61] - 1 if len(c) > 61 else np.nan,
            "off_hi120": c[-1] / np.nanmax(c[-120:]) - 1,
            "off_hi250": c[-1] / np.nanmax(c[-250:]) - 1,
            "vol_exp": np.nanmean(v[-20:]) / v100 if v100 > 0 else np.nan,
            "stale_days": int((asof - g["date"].iloc[-1]).days),
        })
    return pd.DataFrame(rows), asof


def earnings_features(ann: pd.DataFrame, asof) -> pd.DataFrame:
    """Latest reported quarter vs the same quarter a year earlier.

    Built from the raw EPS series, NOT AKD's unconsolidatedQuarterEpsYOY field —
    that field is only populated for 2018-19 (1,815 and 1,837 filings) and then
    collapses to ~10/year, which silently reduces the sample to nothing.
    """
    fr = ann[ann["ann_family"].str.startswith("FR", na=False)].copy()
    fr = fr.dropna(subset=["unconsolidatedQuarterEps", "periodEndDate"])
    if fr.empty:
        return pd.DataFrame(columns=["symbol"])
    fr["pm"] = fr["periodEndDate"].dt.month
    fr["py"] = fr["periodEndDate"].dt.year
    # dedupe on year-MONTH: a company can file an annual and a quarterly whose
    # period ends fall in the same month a day apart (e.g. SANE, Dec 2020)
    fr = (fr.sort_values("date")
            .drop_duplicates(["symbol", "py", "pm"], keep="first")
            .rename(columns={"unconsolidatedQuarterEps": "eps",
                             "unconsolidatedSales": "sales"}))
    prev = fr[["symbol", "pm", "py", "eps", "sales"]].rename(
        columns={"eps": "eps_prev", "sales": "sales_prev"})
    prev["py"] += 1
    m = fr.merge(prev, on=["symbol", "pm", "py"], how="left")
    last = m.sort_values("date").groupby("symbol").tail(1).copy()
    last["eps_delta"] = last["eps"] - last["eps_prev"]
    with np.errstate(divide="ignore", invalid="ignore"):
        last["sales_g"] = last["sales"] / last["sales_prev"] - 1.0
    last["days_since_filing"] = (asof - last["date"]).dt.days
    last["turnaround"] = (last["eps"] > 0) & (last["eps_prev"] <= 0)
    return last[["symbol", "date", "eps", "eps_prev", "eps_delta", "sales_g",
                 "turnaround", "days_since_filing"]].rename(
        columns={"date": "last_filing"})


def fundamentals(d: Path, px: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    p = d / "mbf_fundamentals.csv"
    if not p.exists():
        log("    mbf_fundamentals.csv not found — valuation columns will be blank")
        return pd.DataFrame(columns=["symbol"])
    fd = pd.read_csv(p, low_memory=False)
    fd["period_end"] = pd.to_datetime(fd["period_end"], errors="coerce")
    fd["value"] = num(fd["value"])
    fd = fd.dropna(subset=["period_end", "value"])

    want = ["pe_ratio", "pb_ratio", "roe", "ltde", "cur_ratio", "npm", "bkv"]
    cur = fd[fd["field_key"].isin(want)].sort_values("period_end")
    latest = cur.groupby(["symbol", "field_key"]).tail(1)
    w = latest.pivot_table(index="symbol", columns="field_key", values="value",
                           aggfunc="last")
    w["fund_asof"] = (latest.sort_values("period_end")
                      .groupby("symbol")["period_end"].last())
    # header note 4: these are fractions, the rest are plain ratios
    for c in ("roe", "roa", "npm", "div_yield"):
        if c in w.columns:
            w[c] = w[c] * 100.0

    hist = fd[fd["field_key"].isin(["pe_ratio", "pb_ratio"])]
    hist = hist[hist["value"].between(0.2, 60)]
    w = w.join(hist.pivot_table(index="symbol", columns="field_key",
                                values="value", aggfunc="median")
               .add_suffix("_med"))

    ref = w[["fund_asof"]].dropna().reset_index().sort_values("fund_asof")
    if not ref.empty:
        ref = pd.merge_asof(ref, px[["symbol", "date", "tr_close"]].sort_values("date"),
                            left_on="fund_asof", right_on="date", by="symbol",
                            direction="backward", tolerance=pd.Timedelta(days=120))
        w = w.join(ref.set_index("symbol")["tr_close"].rename("price_then"))

    struct = ev[(ev["bonus_r"] > 0) | (ev["right_r"] > 0)]
    if not struct.empty:
        w = w.join(struct.groupby("symbol")["ex_date"].max().rename("last_struct"))
    return w.reset_index()


# =========================================================== STAGE 3: SCREEN
def screen(pf, ann, ff, prof, ev, asof) -> pd.DataFrame:
    d = pf.copy()
    for extra in (prof, earnings_features(ann, asof), ff):
        if not extra.empty:
            d = d.merge(extra, on="symbol", how="left")
    for col in ("active", "sector_name", "name", "pe_ratio", "pb_ratio", "roe",
                "ltde", "bkv", "pe_ratio_med", "pb_ratio_med", "price_then",
                "fund_asof", "last_struct", "eps", "eps_prev", "eps_delta",
                "sales_g", "turnaround", "days_since_filing", "last_filing"):
        if col not in d.columns:
            d[col] = np.nan

    n0 = len(d)
    d = d[(d["price"] >= MIN_PRICE) & (d["turnover20"] >= MIN_TURNOVER)
          & (d["traded_frac60"] >= MIN_TRADED_FRAC)
          & (d["stale_days"] <= MAX_STALE_DAYS)
          & (d["active"] != False)].copy()               # noqa: E712
    log(f"    tradeable universe: {len(d)} of {n0}")

    with np.errstate(divide="ignore", invalid="ignore"):
        d["reprice_x"] = d["price"] / d["price_then"]
        d["pe_now"] = d["pe_ratio"] * d["reprice_x"]
        d["pb_now"] = d["pb_ratio"] * d["reprice_x"]
        d["eps_yield_chk"] = d["eps"] * 4 / d["price"]

    d["struct_changed"] = (d["last_struct"].notna() & d["fund_asof"].notna()
                           & (d["last_struct"] > d["fund_asof"]))
    d["reprice_odd"] = (~d["reprice_x"].between(0.30, 3.5)) & d["reprice_x"].notna()
    bad = d["struct_changed"] | d["reprice_odd"]
    d.loc[~d["pe_now"].between(*PE_OK) | bad, "pe_now"] = np.nan
    d.loc[~d["pb_now"].between(*PB_OK) | bad, "pb_now"] = np.nan
    d.loc[~d["eps_yield_chk"].between(*EPS_YIELD_OK),
          ["eps", "eps_prev", "eps_delta"]] = np.nan
    d.loc[d["days_since_filing"] > MAX_FILING_AGE,
          ["eps", "eps_prev", "eps_delta", "sales_g"]] = np.nan
    log(f"    ratios voided for {int(bad.sum())} names "
        f"(capital structure changed or implausible re-price)")

    with np.errstate(divide="ignore", invalid="ignore"):
        d["pb_vs_own"] = d["pb_now"] / d["pb_ratio_med"] - 1.0
        d["pe_vs_own"] = d["pe_now"] / d["pe_ratio_med"] - 1.0
        d["eps_surp"] = d["eps_delta"] / d["price"]
        d["earn_yield"] = np.where(d["pe_now"] > 0, 1 / d["pe_now"], np.nan)
    sec = d.groupby("sector_name")["pb_now"].transform("median")
    d["pb_vs_sector"] = d["pb_now"] / sec - 1.0

    def pct(s, invert=False):
        r = s.rank(pct=True)
        return (1 - r) if invert else r

    C = pd.DataFrame(index=d.index)
    C["drawdown"] = pct(d["off_hi250"], invert=True)
    C["earn_surprise"] = pct(d["eps_surp"])
    C["cheap_own_pb"] = pct(d["pb_vs_own"], invert=True)
    C["earn_yield"] = pct(d["earn_yield"])
    C["cheap_sector"] = pct(d["pb_vs_sector"], invert=True)
    C["sales_growth"] = pct(d["sales_g"])
    C["quality_roe"] = pct(d["roe"])
    d["data_cov"] = (C.notna().mul(pd.Series(WEIGHTS)).sum(axis=1) * 100).round(0)
    C = C.fillna(0.5)
    d["score"] = (sum(C[k] * w for k, w in WEIGHTS.items()) * 100).round(1)

    um = set(ann[(ann["ann_family"].isin(["MISV", "MIV1"]))
                 & ann["title"].astype(str).str.contains("Unusual", case=False, na=False)
                 & (ann["date"] >= asof - pd.Timedelta(days=120))]["symbol"])
    ca = set(ev[ev["ex_date"] >= asof - pd.Timedelta(days=45)]["symbol"])

    def flags(r):
        f = []
        if r["struct_changed"]:
            f.append("VERIFY: bonus/rights after last reported accounts — ratios unreliable")
        if r["reprice_odd"]:
            f.append(f"VERIFY: price moved {r['reprice_x']:.2f}x since last accounts — "
                     f"possible split not in this data")
        if pd.notna(r["off_hi250"]) and r["off_hi250"] < -0.70:
            f.append(f"down {abs(r['off_hi250']):.0%} in 12m — confirm a real fall, not a split")
        if r["symbol"] in um:
            f.append("PSX unusual-movement letter <120d (tested edge -7.9%)")
        if pd.notna(r["vol_exp"]) and r["vol_exp"] > 3:
            f.append(f"volume {r['vol_exp']:.1f}x its 100d norm (tested edge -11.2%)")
        if pd.notna(r["mom60"]) and r["mom60"] > 0.40:
            f.append(f"already +{r['mom60']:.0%} in 60d (momentum edge -3.4%)")
        if r["symbol"] in ca:
            f.append("ex-date within 45d")
        if pd.notna(r["ltde"]) and r["ltde"] > 1.5:
            f.append(f"LT debt/equity {r['ltde']:.1f}")
        if pd.notna(r["atr_pct"]) and r["atr_pct"] > 0.07:
            f.append(f"volatile: ATR {r['atr_pct']:.1%}/day")
        if pd.notna(r["data_cov"]) and r["data_cov"] < 55:
            f.append(f"only {r['data_cov']:.0f}% of score backed by data")
        return " | ".join(f)

    def why(r):
        w = []
        if pd.notna(r["eps_delta"]) and r["eps_delta"] > 0 and pd.notna(r["eps_prev"]):
            w.append(f"quarterly EPS Rs {r['eps']:.2f} vs Rs {r['eps_prev']:.2f} a year "
                     f"earlier, filed {int(r['days_since_filing'])}d ago")
        if r.get("turnaround") is True:
            w.append("loss to profit year-on-year")
        if pd.notna(r["sales_g"]) and r["sales_g"] > 0.10:
            w.append(f"sales +{r['sales_g']:.0%} YoY")
        if pd.notna(r["pe_now"]):
            t = f"P/E {r['pe_now']:.1f}"
            if pd.notna(r["pe_vs_own"]) and r["pe_vs_own"] < -0.20:
                t += f" ({abs(r['pe_vs_own']):.0%} below its 5yr median)"
            w.append(t)
        if pd.notna(r["pb_now"]) and pd.notna(r["pb_vs_own"]) and r["pb_vs_own"] < -0.15:
            w.append(f"P/B {r['pb_now']:.2f}, {abs(r['pb_vs_own']):.0%} below its own "
                     f"5yr median {r['pb_ratio_med']:.2f}")
        if pd.notna(r["pb_vs_sector"]) and r["pb_vs_sector"] < -0.25:
            w.append(f"{abs(r['pb_vs_sector']):.0%} cheaper on P/B than "
                     f"{str(r['sector_name']).title()} peers")
        if pd.notna(r["roe"]) and r["roe"] > 12:
            w.append(f"ROE {r['roe']:.0f}%")
        if pd.notna(r["off_hi250"]) and -0.70 < r["off_hi250"] < -0.20:
            w.append(f"{abs(r['off_hi250']):.0%} below its 12-month high")
        return "; ".join(w) if w else "composite only — no standout driver"

    d["why"] = d.apply(why, axis=1)
    d["caution"] = d.apply(flags, axis=1)
    d["suggested_stop"] = (d["price"] * (1 - K_STOP * d["atr_pct"])).round(2)
    d["suggested_target"] = (d["price"] * (1 + K_TGT * d["atr_pct"])).round(2)
    d["shares_30k"] = (TICKET / d["price"]).astype(int)
    d["verify"] = (d["struct_changed"] | d["reprice_odd"]
                   | (d["off_hi250"] < -0.70)).fillna(False)
    return d.sort_values(["verify", "score"],
                         ascending=[True, False]).reset_index(drop=True)


# =========================================================== STAGE 4: HTML
HTML_TMPL = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Multi Beggar Finder — PSX screen __ASOF__</title><style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1a1a18;--mut:#6b6b66;--line:#e3e3df;
--pos:#1c7d54;--neg:#b4342a;--warn:#8a5a00;--warnbg:#fdf6e3;--accent:#2b5d8a}
@media(prefers-color-scheme:dark){:root{--bg:#16171a;--card:#1e2024;--ink:#e9e9e6;
--mut:#9a9a94;--line:#2e3136;--pos:#4ec08a;--neg:#e8776c;--warn:#d9a640;
--warnbg:#2a2418;--accent:#7fb2dd}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1560px;margin:0 auto;padding:22px 18px 70px}
h1{font-size:21px;margin:0 0 3px;letter-spacing:-.2px}
.sub{color:var(--mut);font-size:12.5px;margin-bottom:16px}
.note{background:var(--warnbg);border:1px solid var(--line);border-left:3px solid var(--warn);
padding:11px 14px;border-radius:5px;font-size:12.5px;margin-bottom:16px}.note b{color:var(--warn)}
.ctl{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin-bottom:13px}
input,select{background:var(--card);color:var(--ink);border:1px solid var(--line);
border-radius:5px;padding:6px 9px;font-size:13px;font-family:inherit}
input[type=text]{min-width:190px}
label.ck{display:flex;gap:5px;align-items:center;font-size:12.5px;color:var(--mut);cursor:pointer}
.cnt{color:var(--mut);font-size:12.5px;margin-left:auto}
table{width:100%;border-collapse:collapse;background:var(--card);
border:1px solid var(--line);border-radius:7px;overflow:hidden}
th{background:var(--bg);text-align:left;font-size:11px;text-transform:uppercase;
letter-spacing:.055em;color:var(--mut);padding:9px 10px;border-bottom:1px solid var(--line);
cursor:pointer;white-space:nowrap;position:sticky;top:0;z-index:2}th:hover{color:var(--ink)}
td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top;font-size:13px}
tr:last-child td{border-bottom:none}
.sym{font-weight:650;font-size:14px}.nm{color:var(--mut);font-size:11.5px;display:block;max-width:210px}
.sec{color:var(--mut);font-size:11px}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.why{max-width:430px;font-size:12.5px;line-height:1.48}
.flag{max-width:290px;font-size:11.5px;color:var(--warn);line-height:1.45}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.bar{position:relative;min-width:64px}
.bar i{display:block;height:4px;background:var(--accent);border-radius:2px;margin-top:3px}
.lvl{font-size:11.5px;color:var(--mut);white-space:nowrap}.lvl b{color:var(--ink);font-weight:600}
.badge{display:inline-block;background:var(--bg);border:1px solid var(--line);
border-radius:3px;padding:0 5px;font-size:10.5px;color:var(--mut);margin-left:5px}
.vfy td{opacity:.62}
footer{margin-top:22px;color:var(--mut);font-size:11.5px;line-height:1.7}
</style></head><body><div class="wrap">
<h1>Multi Beggar Finder</h1>
<div class="sub">PSX research funnel &middot; prices as of <b>__ASOF__</b> &middot;
__N__ tradeable names screened</div>
<div class="note"><b>Read this first.</b> A shortlist to research, not a buy list. No
component here has demonstrated out-of-sample edge — the one that survived holdout
testing was deep-drawdown mean reversion (+6.5% CAGR vs +0.2% random) and carries the
heaviest weight at 28%. Base rate for any liquid PSX stock touching +10% within 60
trading days is <b>65%</b>; doing it before falling 8% is only <b>44%</b>. Greyed rows
need a corporate-action check before their ratios mean anything. Not investment advice.</div>
<div class="ctl">
<input type="text" id="q" placeholder="Search symbol or name…">
<select id="sec"><option value="">All sectors</option>__SECTORS__</select>
<select id="pmax"><option value="">Any price</option><option value="10">under Rs 10</option>
<option value="30">under Rs 30</option><option value="75">under Rs 75</option>
<option value="200">under Rs 200</option></select>
<select id="smin"><option value="0">Any score</option><option value="55">score 55+</option>
<option value="62">score 62+</option><option value="68">score 68+</option></select>
<label class="ck"><input type="checkbox" id="clean" checked> hide names needing verification</label>
<label class="ck"><input type="checkbox" id="nocaut"> hide any with caution flags</label>
<label class="ck"><input type="checkbox" id="cov"> require 80%+ data coverage</label>
<span class="cnt" id="cnt"></span></div>
<table><thead><tr>
<th data-k="score">Score</th><th data-k="symbol">Symbol</th><th data-k="price" class="num">Price</th>
<th data-k="pe_now" class="num">P/E</th><th data-k="pb_now" class="num">P/B</th>
<th data-k="roe" class="num">ROE</th><th data-k="off_hi250" class="num">off 12m hi</th>
<th data-k="mom60" class="num">60d</th><th data-k="turnover20" class="num">Rs m/day</th>
<th data-k="why">Why it is on the list</th><th data-k="caution">Check before you act</th>
<th data-k="atr_pct">Levels &middot; Rs 30k</th></tr></thead><tbody id="tb"></tbody></table>
<footer>Weights: drawdown vs 12-month high 28%, year-on-year quarterly EPS surprise 20%,
P/B vs own 5-year median 15%, earnings yield 12%, P/B vs sector 10%, sales growth 8%,
ROE 7%. Missing inputs score neutral; the data-coverage figure shows how much of each
score rests on real data.<br>Suggested stop is 2.5&times;ATR20 below price, target
3.0&times;ATR20 above — the median PSX stock moves 4.19% a day, so a conventional 8% stop
sits inside the noise and loses 0.95% per trade on random entries.<br>Cautions were
measured as <i>negative</i> edge: volume expansion &minus;11.2% (z&nbsp;=&nbsp;&minus;7.8),
60-day momentum chasing &minus;3.4% (z&nbsp;=&nbsp;&minus;16.0), PSX unusual-movement
letters &minus;7.9% (z&nbsp;=&nbsp;&minus;3.8).</footer></div><script>
const D=__DATA__;const f=(v,d=2)=>v==null||isNaN(v)?'&ndash;':(+v).toFixed(d);
const pc=v=>v==null||isNaN(v)?'&ndash;':(v*100).toFixed(0)+'%';
const sgn=v=>v==null||isNaN(v)?'':(v<0?'neg':'pos');let sk='score',sd=-1;
function draw(){const q=document.getElementById('q').value.toLowerCase().trim();
const sc=document.getElementById('sec').value;
const pm=parseFloat(document.getElementById('pmax').value)||1e9;
const sm=parseFloat(document.getElementById('smin').value)||0;
const cl=document.getElementById('clean').checked,nc=document.getElementById('nocaut').checked,
cv=document.getElementById('cov').checked;
let r=D.filter(x=>{if(cl&&x.verify)return false;if(nc&&x.caution)return false;
if(cv&&(x.data_cov||0)<80)return false;if(x.price>pm)return false;
if((x.score||0)<sm)return false;if(sc&&x.sector_name!==sc)return false;
if(q&&!((x.symbol||'').toLowerCase().includes(q)||(x.name||'').toLowerCase().includes(q)))return false;
return true;});
r.sort((a,b)=>{let u=a[sk],v=b[sk];if(u==null)return 1;if(v==null)return -1;
return typeof u==='string'?sd*u.localeCompare(v):sd*(u-v);});
document.getElementById('cnt').textContent=r.length+' of '+D.length+' shown';
document.getElementById('tb').innerHTML=r.map(x=>`<tr class="${x.verify?'vfy':''}">
<td class="bar"><b>${f(x.score,1)}</b><i style="width:${Math.max(4,(x.score||0))}%"></i>
<div class="sec">${f(x.data_cov,0)}% data</div></td>
<td><span class="sym">${x.symbol}</span><span class="nm">${x.name||''}</span>
<span class="sec">${x.sector_name||''}</span></td>
<td class="num">${f(x.price)}</td><td class="num">${f(x.pe_now,1)}</td>
<td class="num">${f(x.pb_now)}</td><td class="num">${x.roe==null?'&ndash;':f(x.roe,0)+'%'}</td>
<td class="num ${sgn(x.off_hi250)}">${pc(x.off_hi250)}</td>
<td class="num ${sgn(x.mom60)}">${pc(x.mom60)}</td><td class="num">${f(x.turnover20,1)}</td>
<td class="why">${x.why||''}</td><td class="flag">${x.caution||''}</td>
<td class="lvl">stop <b>${f(x.suggested_stop)}</b> &middot; target <b>${f(x.suggested_target)}</b>
<br>ATR ${pc(x.atr_pct)}/day<span class="badge">${x.shares_30k} sh</span></td></tr>`).join('');}
document.querySelectorAll('th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;
sd=(k===sk)?-sd:(k==='symbol'||k==='why'||k==='caution'?1:-1);sk=k;draw();});
['q','sec','pmax','smin','clean','nocaut','cov'].forEach(id=>{const e=document.getElementById(id);
e.addEventListener(e.type==='checkbox'?'change':'input',draw);e.addEventListener('change',draw);});
draw();</script></body></html>"""


def write_html(d: pd.DataFrame, asof, out: Path) -> Path:
    cols = ["symbol", "name", "sector_name", "price", "score", "data_cov", "why",
            "caution", "pe_now", "pb_now", "roe", "off_hi250", "mom60",
            "atr_pct", "turnover20", "suggested_stop", "suggested_target",
            "shares_30k", "verify"]
    t = d.reindex(columns=cols).copy()
    t["sector_name"] = t["sector_name"].fillna("—").astype(str).str.title()
    t["name"] = t["name"].fillna("").astype(str)
    for c in ("pe_now", "pb_now", "roe", "off_hi250", "mom60", "atr_pct",
              "price", "suggested_stop", "suggested_target", "score", "data_cov"):
        t[c] = num(t[c]).round(3)
    t["turnover20"] = (num(t["turnover20"]) / 1e6).round(2)
    t["verify"] = t["verify"].fillna(False).astype(bool)
    t = t.where(pd.notna(t), None)
    rows = json.loads(t.to_json(orient="records"))
    secs = sorted({r["sector_name"] for r in rows if r["sector_name"]})
    html = (HTML_TMPL.replace("__DATA__", json.dumps(rows))
            .replace("__ASOF__", str(pd.Timestamp(asof).date()))
            .replace("__N__", str(len(rows)))
            .replace("__SECTORS__", "".join(f"<option>{s}</option>" for s in secs)))
    out.write_text(html, encoding="utf-8")
    return out


# ================================================================= MAIN
def find_dir(arg) -> Path:
    if arg:
        return Path(arg).expanduser()
    here = Path(__file__).resolve().parent
    for cand in (here, here / "raw", here.parent,
                 Path("D:/Investments/Multi Beggar Finder")):
        if (cand / "mbf_prices.csv").exists():
            return cand
    return here


def main():
    ap = argparse.ArgumentParser(description="Rebuild the Multi Beggar Finder screen.")
    ap.add_argument("--dir", help="folder holding the mbf_*.csv files")
    ap.add_argument("--check", action="store_true", help="validate inputs and stop")
    ap.add_argument("--top", type=int, default=15, help="rows to print (default 15)")
    a = ap.parse_args()

    d = find_dir(a.dir)
    log(f"\nMulti Beggar Finder — refresh\nfolder: {d}\n")

    missing = [f for f in REQUIRED if not (d / f).exists()]
    if missing:
        sys.exit(f"Missing required file(s): {', '.join(missing)}\n"
                 f"Run AKD_PULL.js in the browser first, then move the downloads "
                 f"into:\n  {d}")
    for f in REQUIRED + OPTIONAL:
        p = d / f
        log(f"  {'OK  ' if p.exists() else 'none'} {f:26s}"
            + (f"{p.stat().st_size / 1048576:8.1f} MB" if p.exists() else ""))
    if a.check:
        log("\n--check: inputs look readable. Stopping.")
        return

    log("\n[1/4] announcements")
    ann = load_announcements(d)
    ev = payout_events(ann)
    log(f"    {len(ann):,} rows, {ann['symbol'].nunique()} symbols, "
        f"{ann['date'].min().date()} -> {ann['date'].max().date()}")
    log(f"    {len(ev):,} payout/ex-date events")

    log("[2/4] prices")
    px = deadjust(load_prices(d), ev)
    verify_deadjust(px, ev)
    log(f"    {len(px):,} bars, {px['symbol'].nunique()} symbols, "
        f"latest {px['date'].max().date()}")

    log("[3/4] features + screen")
    pf, asof = price_features(px)
    ff = fundamentals(d, px, ev)
    res = screen(pf, ann, ff, load_profiles(d), ev, asof)

    log("[4/4] outputs")
    csv_p = d / "screen_today.csv"
    res.to_csv(csv_p, index=False)
    html_p = write_html(res, asof, d / "mbf_screen.html")
    log(f"    {csv_p.name}")
    log(f"    {html_p.name}   ({html_p.stat().st_size / 1024:.0f} KB)")

    if HAVE_PARQUET:
        wd = d / "work"
        wd.mkdir(exist_ok=True)
        px.to_parquet(wd / "prices.parquet", index=False)
        ann.to_parquet(wd / "announcements.parquet", index=False)
        ev.to_parquet(wd / "payout_events.parquet", index=False)
        load_profiles(d).to_parquet(wd / "profiles.parquet", index=False)
        res.to_parquet(wd / "screen_today.parquet", index=False)
        log(f"    work/*.parquet  (for the research scripts)")
    else:
        log("    (pyarrow not installed — skipped parquet; the screen is unaffected)")

    clean = res[~res["verify"]]
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 88)
    log(f"\nas of {pd.Timestamp(asof).date()} — {len(clean)} clean, "
        f"{int(res['verify'].sum())} parked for verification\n")
    log(clean.head(a.top)[["symbol", "price", "score", "data_cov", "pe_now",
                           "pb_now", "off_hi250", "why"]]
        .to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    log(f"\nOpen {html_p} in a browser.\n")


if __name__ == "__main__":
    main()
