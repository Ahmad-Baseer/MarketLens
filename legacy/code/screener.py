"""
Multi Beggar Finder — the actual tool: a daily ranked candidate list with reasons.

A RESEARCH FUNNEL, not a signal generator. Narrows ~370 tradeable PSX symbols to
a short list and states, in numbers, why each is on it — so the next step is
your own reading of the company.

Ranked on:
  EARNINGS MOMENTUM  latest reported quarter EPS vs the same quarter a year
                     earlier, dated to the filing so the figure was genuinely
                     public at the time
  VALUATION          P/E and P/B taken from AKD's own ratios and re-priced to
                     today, versus the company's own 5-year median and its
                     sector
  DRAWDOWN           how far below its 12-month high it still sits — the only
                     component that survived out-of-sample testing
  QUALITY            ROE, leverage and liquidity gates

Deliberately NOT rewarded, because the backtest showed these are negative-edge
on PSX 2021-2026 (see FINDINGS.md). They appear as CAUTION flags instead:
  volume expansion / "dead chart waking up"  edge -11.2%, z=-7.8
  60-day momentum chasing                    edge -3.4%, z=-16.0
  PSX "unusual movement" letters             edge -7.9%, z=-3.8

WHY THE SANITY GATES MATTER
---------------------------
First run put DLL top with "P/E 0.17, P/B 0.07, EPS Rs 288 on a Rs 54 share".
Cause: computing P/E as (my price) / (their per-share EPS). When a company
splits, consolidates or does a big rights issue, those two numbers refer to
DIFFERENT shares and the ratio becomes meaningless — DLL's price went Rs 717.89
-> Rs 53.96 in 250 days (a 13.3x split AKD does not adjust for), and STL had an
85% rights issue at Rs 10 on 2026-08-16. Because "cheap" scores well, every
mishandled corporate action floated straight to the top.

Fix: use AKD's own pe_ratio / pb_ratio (numerator and denominator consistent
with each other at that reporting date) and re-price by the price change since
then. Then apply plausibility windows — anything outside is treated as MISSING
(neutral), never as maximally cheap — and flag names whose capital structure
changed after the last reported fundamentals.
"""
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("/home/claude/mbf/raw")
WORK = Path("/home/claude/mbf/work")
OUT = Path("/home/claude/mbf/out")

MIN_TURNOVER = 300_000
MIN_PRICE = 2.0
MIN_TRADED_FRAC = 0.70
MAX_FILING_AGE = 200          # days; older than this and earnings info is stale

# plausibility windows — outside these a ratio is treated as unknown, not cheap
PE_OK = (2.0, 60.0)
PB_OK = (0.10, 15.0)
EPS_YIELD_OK = (-0.40, 0.50)


def price_features():
    px = pd.read_parquet(WORK / "prices.parquet").sort_values(["symbol", "date"])
    asof = px["date"].max()
    rows = []
    for sym, g in px.groupby("symbol", sort=False):
        g = g.tail(300)
        if len(g) < 130:
            continue
        # tr_close (AKD's own adjusted series) for drawdown: payouts removed, so
        # the number reflects actual capital loss rather than dividends paid out
        c = g["tr_close"].to_numpy(float)
        praw = g["px_close"].to_numpy(float)
        h, l = g["px_high"].to_numpy(float), g["px_low"].to_numpy(float)
        v, turn = g["volume"].to_numpy(float), g["turnover"].to_numpy(float)
        traded = g["traded"].to_numpy(float)
        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        rows.append({
            "symbol": sym, "last_date": g["date"].iloc[-1], "price": praw[-1],
            "atr_pct": np.nanmean(tr[-20:]) / praw[-1] if praw[-1] > 0 else np.nan,
            "turnover20": float(np.median(turn[-20:])),
            "traded_frac60": float(traded[-60:].mean()),
            "mom20": c[-1] / c[-21] - 1 if len(c) > 21 else np.nan,
            "mom60": c[-1] / c[-61] - 1 if len(c) > 61 else np.nan,
            "off_hi120": c[-1] / np.nanmax(c[-120:]) - 1,
            "off_hi250": c[-1] / np.nanmax(c[-250:]) - 1,
            "vol_exp": (np.nanmean(v[-20:]) / np.nanmean(v[-100:])
                        if np.nanmean(v[-100:]) > 0 else np.nan),
            "stale_days": int((asof - g["date"].iloc[-1]).days),
        })
    return pd.DataFrame(rows), asof, px


def earnings_features(asof):
    ann = pd.read_parquet(WORK / "announcements.parquet")
    fr = ann[ann["ann_family"].str.startswith("FR", na=False)].copy()
    fr = fr.dropna(subset=["unconsolidatedQuarterEps", "periodEndDate"])
    fr["pm"], fr["py"] = fr["periodEndDate"].dt.month, fr["periodEndDate"].dt.year
    fr = (fr.sort_values("date").drop_duplicates(["symbol", "py", "pm"], keep="first")
            .rename(columns={"unconsolidatedQuarterEps": "eps",
                             "unconsolidatedSales": "sales"}))
    prev = fr[["symbol", "pm", "py", "eps", "sales"]].rename(
        columns={"eps": "eps_prev", "sales": "sales_prev"})
    prev["py"] += 1
    m = fr.merge(prev, on=["symbol", "pm", "py"], how="left")
    latest = m.sort_values("date").groupby("symbol").tail(1).copy()
    latest["eps_delta"] = latest["eps"] - latest["eps_prev"]
    with np.errstate(divide="ignore", invalid="ignore"):
        latest["sales_g"] = latest["sales"] / latest["sales_prev"] - 1.0
    latest["days_since_filing"] = (asof - latest["date"]).dt.days
    latest["turnaround"] = (latest["eps"] > 0) & (latest["eps_prev"] <= 0)
    return latest[["symbol", "date", "eps", "eps_prev", "eps_delta", "sales_g",
                   "turnaround", "days_since_filing"]].rename(
        columns={"date": "last_filing"})


def fundamentals(px: pd.DataFrame):
    """AKD's own ratios at their last reported period, re-priced to today.

    pe_now = pe_then * (price_now / price_then). Both numerator and denominator
    of pe_then refer to the SAME share count, so scaling by the price change is
    valid even if shares later changed — what is NOT valid is mixing today's
    price with a per-share figure from a different share count.
    """
    fd = pd.read_csv(RAW / "mbf_fundamentals.csv", low_memory=False)
    fd["period_end"] = pd.to_datetime(fd["period_end"], errors="coerce")
    fd["value"] = pd.to_numeric(fd["value"], errors="coerce")
    fd = fd.dropna(subset=["period_end", "value"])

    want = ["pe_ratio", "pb_ratio", "roe", "ltde", "cur_ratio", "npm", "shares", "bkv"]
    cur = fd[fd["field_key"].isin(want)].sort_values("period_end")
    latest = cur.groupby(["symbol", "field_key"]).tail(1)
    w = latest.pivot_table(index="symbol", columns="field_key", values="value",
                           aggfunc="last")
    w["fund_asof"] = (latest.sort_values("period_end").groupby("symbol")["period_end"]
                      .last())

    # AKD stores roe/roa/npm/div_yield as FRACTIONS (median roe = 0.0811), while
    # ltde/cur_ratio/pe/pb are plain ratios. Without this the roe>12 test never
    # fires and the column renders as 0%.
    for c in ("roe", "roa", "npm", "div_yield"):
        if c in w.columns:
            w[c] = w[c] * 100.0

    # own-history medians for a like-for-like "cheap vs itself"
    hist = fd[fd["field_key"].isin(["pe_ratio", "pb_ratio"])]
    hist = hist[hist["value"].between(0.2, 60)]
    hm = hist.pivot_table(index="symbol", columns="field_key", values="value",
                          aggfunc="median").add_suffix("_med")
    w = w.join(hm)

    # price on (or just before) the fundamentals date, from the adjusted series
    p = px[["symbol", "date", "tr_close"]].sort_values("date")
    ref = w[["fund_asof"]].dropna().reset_index().sort_values("fund_asof")
    ref = pd.merge_asof(ref, p, left_on="fund_asof", right_on="date",
                        by="symbol", direction="backward",
                        tolerance=pd.Timedelta(days=120))
    w = w.join(ref.set_index("symbol")["tr_close"].rename("price_then"))

    # detect capital-structure change AFTER the fundamentals date
    ev = pd.read_parquet(WORK / "payout_events.parquet")
    struct = ev[(ev["bonus_r"] > 0) | (ev["right_r"] > 0)]
    w = w.join(struct.groupby("symbol")["ex_date"].max().rename("last_struct"))
    return w.reset_index()


def build():
    pf, asof, px = price_features()
    d = (pf.merge(pd.read_parquet(WORK / "profiles.parquet"), on="symbol", how="left")
           .merge(earnings_features(asof), on="symbol", how="left")
           .merge(fundamentals(px), on="symbol", how="left"))

    n0 = len(d)
    d = d[(d["price"] >= MIN_PRICE) & (d["turnover20"] >= MIN_TURNOVER)
          & (d["traded_frac60"] >= MIN_TRADED_FRAC) & (d["stale_days"] <= 5)
          & (d["active"] != False)].copy()  # noqa: E712
    print(f"tradeable universe: {len(d)} of {n0}")

    # ---- re-priced ratios + plausibility gating -------------------------
    with np.errstate(divide="ignore", invalid="ignore"):
        rp = d["price"] / d["price_then"]
        d["reprice_x"] = rp
        d["pe_now"] = d["pe_ratio"] * rp
        d["pb_now"] = d["pb_ratio"] * rp
        d["eps_yield_chk"] = d["eps"] * 4 / d["price"]

    # capital structure changed after last fundamentals -> ratios unreliable
    d["struct_changed"] = (d["last_struct"].notna()
                           & d["fund_asof"].notna()
                           & (d["last_struct"] > d["fund_asof"]))
    # a >70% move since the fundamentals date usually means a split/consolidation
    # that is not in this data at all
    d["reprice_odd"] = (~d["reprice_x"].between(0.30, 3.5)) & d["reprice_x"].notna()

    bad = d["struct_changed"] | d["reprice_odd"]
    d.loc[~d["pe_now"].between(*PE_OK) | bad, "pe_now"] = np.nan
    d.loc[~d["pb_now"].between(*PB_OK) | bad, "pb_now"] = np.nan
    # implausible EPS (annual figure filed as quarterly, or pre-split) -> drop it
    d.loc[~d["eps_yield_chk"].between(*EPS_YIELD_OK), ["eps", "eps_prev",
                                                       "eps_delta"]] = np.nan
    d.loc[d["days_since_filing"] > MAX_FILING_AGE,
          ["eps", "eps_prev", "eps_delta", "sales_g"]] = np.nan
    print(f"  ratios voided for {int(bad.sum())} names "
          f"(capital structure changed or implausible re-price)")

    with np.errstate(divide="ignore", invalid="ignore"):
        d["pb_vs_own"] = d["pb_now"] / d["pb_ratio_med"] - 1.0
        d["pe_vs_own"] = d["pe_now"] / d["pe_ratio_med"] - 1.0
        d["eps_surp"] = d["eps_delta"] / d["price"]
        d["earn_yield"] = np.where(d["pe_now"] > 0, 1 / d["pe_now"], np.nan)
    d["pb_vs_sector"] = d["pb_now"] / d.groupby("sector_name")["pb_now"].transform("median") - 1

    # ---- score ----------------------------------------------------------
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
    W = {"drawdown": 0.28, "earn_surprise": 0.20, "cheap_own_pb": 0.15,
         "earn_yield": 0.12, "cheap_sector": 0.10, "sales_growth": 0.08,
         "quality_roe": 0.07}
    # how much of the score rests on real data vs neutral fill
    d["data_cov"] = (C.notna().mul(pd.Series(W)).sum(axis=1) * 100).round(0)
    C = C.fillna(0.5)
    d["score"] = (sum(C[k] * w for k, w in W.items()) * 100).round(1)
    for k in W:
        d[f"c_{k}"] = (C[k] * 100).round(0)

    # ---- flags ----------------------------------------------------------
    ann = pd.read_parquet(WORK / "announcements.parquet")
    ev = pd.read_parquet(WORK / "payout_events.parquet")
    um = set(ann[(ann["ann_family"].isin(["MISV", "MIV1"]))
                 & ann["title"].str.contains("Unusual", case=False, na=False)
                 & (ann["date"] >= asof - pd.Timedelta(days=120))]["symbol"])
    ca = set(ev[ev["ex_date"] >= asof - pd.Timedelta(days=45)]["symbol"])

    def flags(r):
        f = []
        if r["struct_changed"]:
            f.append("VERIFY: bonus/rights after last reported accounts — "
                     "ratios unreliable")
        if r["reprice_odd"]:
            f.append(f"VERIFY: price moved {r['reprice_x']:.2f}x since last "
                     f"accounts — possible split not in this data")
        if pd.notna(r["off_hi250"]) and r["off_hi250"] < -0.70:
            f.append(f"down {abs(r['off_hi250']):.0%} in 12m — confirm this is a "
                     f"real fall, not a split")
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
        if r["data_cov"] < 55:
            f.append(f"only {r['data_cov']:.0f}% of score backed by data")
        return " | ".join(f)

    def why(r):
        w = []
        if pd.notna(r["eps_delta"]) and r["eps_delta"] > 0 and pd.notna(r["eps_prev"]):
            w.append(f"quarterly EPS Rs {r['eps']:.2f} vs Rs {r['eps_prev']:.2f} a "
                     f"year earlier, filed {int(r['days_since_filing'])}d ago")
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
    d["suggested_stop"] = (d["price"] * (1 - 2.5 * d["atr_pct"])).round(2)
    d["suggested_target"] = (d["price"] * (1 + 3.0 * d["atr_pct"])).round(2)
    d["shares_30k"] = (30_000 / d["price"]).astype(int)
    d["verify"] = d["struct_changed"] | d["reprice_odd"] | (d["off_hi250"] < -0.70)
    return d.sort_values(["verify", "score"], ascending=[True, False]).reset_index(drop=True), asof


def main():
    d, asof = build()
    cols = ["symbol", "name", "sector_name", "price", "score", "data_cov", "why",
            "caution", "pe_now", "pb_now", "pb_ratio_med", "roe", "eps", "eps_prev",
            "sales_g", "off_hi250", "mom60", "atr_pct", "turnover20",
            "suggested_stop", "suggested_target", "shares_30k",
            "days_since_filing", "last_filing", "verify"]
    d[cols].to_csv(OUT / "screen_today.csv", index=False)
    d.to_parquet(WORK / "screen_today.parquet", index=False)
    clean = d[~d["verify"]]
    pd.set_option("display.width", 250, "display.max_colwidth", 95)
    print(f"\nas of {pd.Timestamp(asof).date()} — {len(clean)} clean, "
          f"{int(d['verify'].sum())} parked for verification\n")
    print(clean.head(15)[["symbol", "price", "score", "data_cov", "pe_now",
                          "pb_now", "off_hi250", "why"]]
          .to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print(f"\nwrote {OUT}/screen_today.csv")


if __name__ == "__main__":
    main()
