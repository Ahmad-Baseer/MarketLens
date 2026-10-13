"""
Multi Beggar Finder — Stage 4: test candidate signals against a MATCHED control.

Every signal is scored as a DIFFERENCE against comparable bars — same year,
same price bucket, same liquidity quartile, same volatility quartile — weighted
to the signal's own composition. Scoring against the unconditional average is
how a signal takes credit for the bull market it happened to fire in.

Reported per signal:
    n            how many entries it would have produced in ~4.7 years
    P_win        P(target before stop) under ATR 2.5x/3.0x
    ctrl         the same for matched control bars
    edge         P_win - ctrl
    z            edge / binomial se  (|z| < 2 is noise; treat < 3 with suspicion
                 given how many signals are being screened here)
    net          expectancy per trade after 1.2% friction
    ctrl_net     matched control expectancy
    yrs+         how many of the 5 calendar years had a positive edge

A signal is only interesting if the edge is positive, z is large, AND yrs+ is
4 or 5. Anything that works in two years out of five is noise.
"""
from pathlib import Path as _P

def _base():
    """Resolve the data folder wherever this script has been copied to.
    Looks for work/ next to the script, then one level up, then the default
    Windows folder — so the same file runs in the sandbox and on your machine."""
    here = _P(__file__).resolve().parent
    for c in (here, here.parent, _P("D:/Investments/Multi Beggar Finder")):
        if (c / "work").is_dir():
            return c
    return here

_BASE = _base()

import numpy as np
import pandas as pd

WORK = _BASE / "work"
OUT = _BASE / "out"
FRICTION = 0.012
WIN, LOSS, PNL = "win_atr", "loss_atr", "pnl_atr"


def load():
    p = pd.read_parquet(WORK / "panel.parquet")
    p["price_bkt"] = pd.cut(p["close"], [0, 5, 10, 20, 30, 50, 100, 300, np.inf])
    p["liq_bkt"] = pd.qcut(p["med_turnover"], 4, labels=False, duplicates="drop")
    p["atr_bkt"] = pd.qcut(p["atr_pct"], 4, labels=False, duplicates="drop")
    ann = pd.read_parquet(WORK / "announcements.parquet")
    return p, ann


STRATA = ["year", "price_bkt", "liq_bkt", "atr_bkt"]


def control(p: pd.DataFrame, sel: pd.DataFrame) -> dict:
    """Composition-weighted control using the signal's own strata mix."""
    w = sel.groupby(STRATA, observed=True).size().rename("w")
    agg = p.groupby(STRATA, observed=True).agg(
        P=(WIN, "mean"), E=(PNL, "mean"), n=(WIN, "size"))
    j = agg.join(w, how="inner")
    j = j[j["n"] >= 20]
    if j.empty or j["w"].sum() == 0:
        return {"P": np.nan, "E": np.nan}
    wt = j["w"] / j["w"].sum()
    return {"P": float((j["P"] * wt).sum()), "E": float((j["E"] * wt).sum())}


def score(p, sel, name):
    n = len(sel)
    if n < 150:
        return {"signal": name, "n": n, "note": "too few entries"}
    c = control(p, sel)
    P = sel[WIN].mean()
    E = sel[PNL].mean()
    edge = P - c["P"]
    se = np.sqrt(max(P * (1 - P), 1e-9) / n)
    # per-year edge sign
    yrs = 0
    tot = 0
    for y, g in sel.groupby("year"):
        if len(g) < 40:
            continue
        cy = control(p[p["year"] == y], g)
        if np.isfinite(cy["P"]):
            tot += 1
            yrs += int(g[WIN].mean() > cy["P"])
    return {"signal": name, "n": n, "P_win": P, "ctrl": c["P"], "edge": edge,
            "z": edge / se if se else np.nan, "net": E - FRICTION,
            "ctrl_net": c["E"] - FRICTION, "yrs+": f"{yrs}/{tot}",
            "med_days": sel.loc[sel[WIN], "days_to_tgt"].median()}


# --------------------------------------------------------------- event signals
def pead_events(ann: pd.DataFrame) -> pd.DataFrame:
    """Post-earnings drift, with the year-on-year comparison built from the EPS
    time series rather than AKD's `unconsolidatedQuarterEpsYOY` field.

    That field is only populated for 2018-2019 (1,815 and 1,837 filings) and
    then collapses to ~10/year from 2020 on, so using it silently restricts the
    study to pre-panel years — which is exactly what produced 13 usable events
    on the first run. Raw `unconsolidatedQuarterEps` IS complete (~1,900/yr
    through 2026), so we self-join it on (symbol, period month, year-1).
    """
    fr = ann[ann["ann_family"].str.startswith("FR", na=False)].copy()
    fr = fr.dropna(subset=["unconsolidatedQuarterEps", "periodEndDate"])
    fr = fr[["symbol", "date", "periodEndDate", "unconsolidatedQuarterEps",
             "unconsolidatedSales", "unconsolidatedPat"]]
    fr = fr.rename(columns={"date": "signal_date",
                            "unconsolidatedQuarterEps": "eps",
                            "unconsolidatedSales": "sales",
                            "unconsolidatedPat": "pat"})
    fr["pm"] = fr["periodEndDate"].dt.month
    fr["py"] = fr["periodEndDate"].dt.year
    # One record per (symbol, reporting year-month), earliest filing wins.
    # Deduping on the exact periodEndDate is not enough: a company can file an
    # annual and a quarterly whose period ends fall in the same month a day
    # apart (e.g. SANE, Dec 2020), which breaks the year-on-year self-join.
    fr = (fr.sort_values("signal_date")
            .drop_duplicates(["symbol", "py", "pm"], keep="first"))

    prev = fr[["symbol", "pm", "py", "eps", "sales", "pat"]].rename(
        columns={"eps": "eps_prev", "sales": "sales_prev", "pat": "pat_prev"})
    prev["py"] = prev["py"] + 1                       # match onto the NEXT year
    m = fr.merge(prev, on=["symbol", "pm", "py"], how="left", validate="1:1")

    m["eps_delta"] = m["eps"] - m["eps_prev"]
    m["turnaround"] = (m["eps"] > 0) & (m["eps_prev"] <= 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        m["sales_g"] = m["sales"] / m["sales_prev"] - 1.0
    return m.dropna(subset=["eps_prev"])


def unusual_movement(ann: pd.DataFrame) -> pd.DataFrame:
    """PSX 'Unusual Movement in the Price of the Shares' letters.

    NOTE: these are announcementType MISV001/MIV1025, NOT the PSX_NOTICE family
    (which turned out to be buy-backs and voluntary delistings). 860 notices
    across 345 symbols, concentrated 2023-2026.
    """
    mi = ann[ann["ann_family"].isin(["MISV", "MIV1"])]
    um = mi[mi["title"].str.contains("Unusual", case=False, na=False)]
    return (um[["symbol", "date"]].rename(columns={"date": "signal_date"})
            .drop_duplicates().reset_index(drop=True))


def attach(p: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Snap each event to the first panel bar on/after the event date."""
    b = p.sort_values("date")
    e = ev.dropna(subset=["symbol", "signal_date"]).sort_values("signal_date")
    m = pd.merge_asof(e, b, left_on="signal_date", right_on="date", by="symbol",
                      direction="forward", tolerance=pd.Timedelta(days=10))
    return m.dropna(subset=[PNL])


def main():
    p, ann = load()
    print(f"panel {len(p):,} rows | random-entry P_win={p[WIN].mean():.3f} "
          f"net={p[PNL].mean()-FRICTION:+.4f}\n")
    rows = []

    # ---- 1. post-earnings drift, by surprise strength -----------------------
    ev = pead_events(ann)
    pe = attach(p, ev)
    pe["surp"] = pe["eps_delta"] / pe["close"]
    print(f"earnings events with YoY comparison: {len(ev):,}  "
          f"-> matched to panel bars: {len(pe):,}")
    rows.append(score(p, pe, "PEAD: any earnings filing"))
    if len(pe) > 1500:
        q = pe["surp"].quantile([.2, .4, .6, .8]).values
        rows.append(score(p, pe[pe["surp"] > q[3]], "PEAD: surprise top quintile"))
        rows.append(score(p, pe[pe["surp"] < q[0]], "PEAD: surprise bottom quintile"))
        rows.append(score(p, pe[pe["turnaround"]], "PEAD: loss -> profit turnaround"))
        rows.append(score(p, pe[(pe["surp"] > q[3]) & (pe["mom60"] < 0.10)],
                          "PEAD: top-quintile surprise + not already run"))
        rows.append(score(p, pe[(pe["surp"] > q[3]) & (pe["off_hi120"] < -0.20)],
                          "PEAD: top-quintile surprise + >20% off 120d high"))
        rows.append(score(p, pe[(pe["surp"] > q[3]) & (pe["mom60"] < -0.05)],
                          "PEAD: top-quintile surprise + falling 60d"))
        rows.append(score(p, pe[pe["sales_g"] > 0.25], "PEAD: sales growth > 25% YoY"))

    # ---- 2. PSX unusual-movement letters (Gemini called these an ENTRY) -----
    um = unusual_movement(ann)
    pn = attach(p, um)
    print(f"unusual-movement notices: {len(um):,} -> matched: {len(pn):,}")
    rows.append(score(p, pn, "PSX 'Unusual Movement' letter"))

    # ---- 3. volume expansion off a base ------------------------------------
    rows.append(score(p, p[p["vol_exp"] > 2], "Volume 20d/100d > 2x"))
    rows.append(score(p, p[p["vol_exp"] > 3], "Volume 20d/100d > 3x"))
    rows.append(score(p, p[(p["vol_exp"] > 3) & (p["mom20"] > 0)],
                      "Volume > 3x + positive 20d momentum"))
    rows.append(score(p, p[(p["vol_exp"] > 3) & (p["off_hi120"] < -0.30)],
                      "Volume > 3x + >30% off 120d high"))

    # ---- 4. momentum / relative strength -----------------------------------
    rows.append(score(p, p[p["mom60"] > p["mom60"].quantile(.8)], "Momentum 60d top quintile"))
    rows.append(score(p, p[p["mom60"] < p["mom60"].quantile(.2)], "Momentum 60d bottom quintile"))
    rows.append(score(p, p[p["off_hi120"] > -0.05], "Within 5% of 120d high"))
    rows.append(score(p, p[p["off_hi120"] < -0.50], "More than 50% off 120d high"))

    # ---- 5. dead chart waking up -------------------------------------------
    lowvol = p["vol60"] < p["vol60"].quantile(.35)
    rows.append(score(p, p[lowvol & (p["vol_exp"] > 3)], "Quiet chart + volume > 3x"))
    rows.append(score(p, p[lowvol & (p["vol_exp"] > 3) & (p["mom20"] > 0.03)],
                      "Quiet chart + volume > 3x + breaking up"))

    res = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    fmt = {"P_win": "{:.3f}", "ctrl": "{:.3f}", "edge": "{:+.4f}", "z": "{:+.2f}",
           "net": "{:+.4f}", "ctrl_net": "{:+.4f}", "med_days": "{:.0f}"}
    disp = res.copy()
    for k, f in fmt.items():
        if k in disp:
            disp[k] = disp[k].map(lambda v: f.format(v) if pd.notna(v) else "")
    print("\n" + "=" * 130)
    print("SIGNAL SCOREBOARD — ATR 2.5x stop / 3.0x target, 60d time stop, "
          "vs composition-matched control")
    print("=" * 130)
    print(disp.to_string(index=False))
    res.to_csv(OUT / "signal_scoreboard.csv", index=False)
    print(f"\nwrote {OUT}/signal_scoreboard.csv")


if __name__ == "__main__":
    main()
