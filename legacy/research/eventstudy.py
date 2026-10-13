"""
Multi Beggar Finder — Stage 3: event study framework.

One function, used for every signal: given a table of (symbol, signal_date),
report the forward-60d outcome distribution and compare it against the base
rate for *comparable bars* — same year, same price bucket, same liquidity
bucket. Comparing a signal against the unconditional base rate is how people
fool themselves: if a signal only fires in 2024 and 2024 was a bull year, the
signal looks great and has told you nothing.

Usage:
    from eventstudy import load, study
    ctx = load()
    events = ...  # DataFrame[symbol, signal_date, (optional) bucket]
    print(study(ctx, events, name="PEAD high surprise"))
"""
from dataclasses import dataclass
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

HORIZON = 60
TARGET = 0.10
STOP = -0.08


@dataclass
class Ctx:
    bars: pd.DataFrame       # eligible_bars + outcomes, indexed (symbol, date)
    cal: pd.DatetimeIndex


def load() -> Ctx:
    bars = pd.read_parquet(WORK / "eligible_bars.parquet")
    px = pd.read_parquet(WORK / "prices.parquet", columns=["date"])
    cal = pd.DatetimeIndex(np.sort(px["date"].unique()))
    bars = bars.dropna(subset=["ret60"]).copy()
    if "date" not in bars.columns:
        bars["date"] = cal[bars["t"].to_numpy()]
    bars["year"] = bars["date"].dt.year
    # strata for fair comparison
    bars["price_bkt"] = pd.cut(bars["raw_close"], [0, 5, 10, 20, 30, np.inf],
                               labels=["0-5", "5-10", "10-20", "20-30", "30+"])
    bars["liq_bkt"] = pd.qcut(bars["med_value_20d"], 4, labels=["L1", "L2", "L3", "L4"],
                              duplicates="drop")
    return Ctx(bars=bars.set_index(["symbol", "date"]).sort_index(), cal=cal)


def _outcomes(g: pd.DataFrame) -> dict:
    u = g["hit_up"] >= 0
    d = g["hit_dn"] >= 0
    fu = u & (~d | (g["hit_up"] < g["hit_dn"]))
    # expectancy of the mechanical rule: +10% target, -8% stop, else exit at day 60
    pnl = np.where(fu, TARGET, np.where(d, STOP, g["ret60"]))
    return {
        "n": len(g),
        "P_+10_first": fu.mean(),
        "P_stop_first": (d & ~fu).mean(),
        "P_touch_+10": u.mean(),
        "mean_ret60": g["ret60"].mean(),
        "median_ret60": g["ret60"].median(),
        "rule_expectancy": pnl.mean(),
        "mean_MFE": g["mfe"].mean(),
        "mean_MAE": g["mae"].mean(),
    }


def study(ctx: Ctx, events: pd.DataFrame, name: str = "signal",
          price_max: float | None = 30.0) -> pd.DataFrame:
    """events needs columns: symbol, signal_date. Entry is the bar AFTER
    signal_date (the bars table already prices entry at next open)."""
    ev = events.dropna(subset=["symbol", "signal_date"]).copy()
    ev["signal_date"] = pd.to_datetime(ev["signal_date"]).dt.normalize()

    # snap each signal to the first eligible bar on/after the signal date
    b = ctx.bars.reset_index()
    b = b.sort_values(["symbol", "date"])
    ev = ev.sort_values(["symbol", "signal_date"])
    merged = pd.merge_asof(
        ev, b, left_on="signal_date", right_on="date", by="symbol",
        direction="forward", tolerance=pd.Timedelta(days=7),
    ).dropna(subset=["ret60"])

    if price_max is not None:
        merged = merged[merged["raw_close"] <= price_max]
    if merged.empty:
        return pd.DataFrame([{"signal": name, "n": 0, "note": "no matching bars"}])

    sig = _outcomes(merged)

    # stratified control: same year x price bucket x liquidity bucket, weighted
    # to the signal's own composition
    keys = ["year", "price_bkt", "liq_bkt"]
    w = merged.groupby(keys, observed=True).size().rename("w")
    ctrl_all = ctx.bars.reset_index()
    if price_max is not None:
        ctrl_all = ctrl_all[ctrl_all["raw_close"] <= price_max]
    grp = ctrl_all.groupby(keys, observed=True)
    ctrl_rows = grp.apply(lambda g: pd.Series(_outcomes(g)), include_groups=False)
    ctrl = ctrl_rows.join(w, how="inner")
    wt = ctrl["w"] / ctrl["w"].sum()
    ctrl_w = {c: float((ctrl[c] * wt).sum()) for c in
              ["P_+10_first", "P_stop_first", "P_touch_+10", "mean_ret60",
               "median_ret60", "rule_expectancy", "mean_MFE", "mean_MAE"]}
    ctrl_w["n"] = int(ctrl["w"].sum())

    # binomial standard error on the headline metric
    p = sig["P_+10_first"]
    se = float(np.sqrt(max(p * (1 - p), 1e-9) / max(sig["n"], 1)))
    edge = p - ctrl_w["P_+10_first"]

    out = pd.DataFrame([
        {"signal": name, "leg": "SIGNAL", **sig},
        {"signal": name, "leg": "CONTROL (matched)", **ctrl_w},
        {"signal": name, "leg": "EDGE", "n": sig["n"],
         "P_+10_first": edge,
         "rule_expectancy": sig["rule_expectancy"] - ctrl_w["rule_expectancy"],
         "mean_ret60": sig["mean_ret60"] - ctrl_w["mean_ret60"]},
        {"signal": name, "leg": f"se(P)={se:.4f}  edge/se={edge/se if se else float('nan'):.2f}"},
    ])
    return out


def by_year(ctx: Ctx, events: pd.DataFrame, name: str, price_max=30.0) -> pd.DataFrame:
    """Same study split by year — the honesty check. A signal that only works
    in one or two years is noise, however good the pooled number looks."""
    ev = events.copy()
    ev["signal_date"] = pd.to_datetime(ev["signal_date"]).dt.normalize()
    rows = []
    for y, g in ev.groupby(ev["signal_date"].dt.year):
        r = study(ctx, g, name=f"{name} [{y}]", price_max=price_max)
        sig = r[r["leg"] == "SIGNAL"]
        ctl = r[r["leg"] == "CONTROL (matched)"]
        if sig.empty or ctl.empty:
            continue
        rows.append({
            "year": y,
            "n": int(sig["n"].iloc[0]),
            "P_+10_first": float(sig["P_+10_first"].iloc[0]),
            "control": float(ctl["P_+10_first"].iloc[0]),
            "edge": float(sig["P_+10_first"].iloc[0]) - float(ctl["P_+10_first"].iloc[0]),
            "rule_exp": float(sig["rule_expectancy"].iloc[0]),
            "ctrl_exp": float(ctl["rule_expectancy"].iloc[0]),
        })
    return pd.DataFrame(rows)
