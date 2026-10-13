"""Judge a signal honestly.

Every signal trade is compared with a MATCHED CONTROL: the average outcome, under
the same exit rule, of all universe stocks on the SAME DATE in the same
liquidity and volatility bucket. That removes the market's move that day and
the "volatile stocks swing more" effect, so what is left is what the signal
itself adds.

Significance is computed across dates, not trades: signals cluster (many fire
in the same week), and treating them as independent overstates confidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEV_END = pd.Timestamp("2022-12-31")       # development period ends; holdout after
EVENT_DEV_END = pd.Timestamp("2022-12-31")  # event families start 2018 (AKD data)


def add_buckets(f: pd.DataFrame) -> pd.DataFrame:
    """Liquidity bucket by turnover rank; volatility tercile within each day's universe."""
    f = f.copy()
    f["liq_b"] = pd.cut(f["to_rank"], [0, 50, 100, np.inf], labels=False)
    u = f["in_universe"]
    pr = f.loc[u].groupby("date")["atr_pct"].rank(pct=True)
    f["vol_b"] = np.nan
    f.loc[u, "vol_b"] = np.minimum((pr * 3).apply(np.ceil) - 1, 2)
    return f


def control_means(f: pd.DataFrame, out: pd.DataFrame, rule: str) -> pd.Series:
    """Mean net outcome per (date, liq_b, vol_b) over entered universe rows."""
    u = f["in_universe"] & out[f"{rule}__entered"]
    df = pd.DataFrame({"date": f["date"], "liq_b": f["liq_b"], "vol_b": f["vol_b"],
                       "net": out[f"{rule}__net"]})[u]
    return df.groupby(["date", "liq_b", "vol_b"])["net"].agg(["mean", "size"])


def evaluate(f: pd.DataFrame, out: pd.DataFrame, mask: pd.Series, rule: str,
             ctrl: pd.DataFrame | None = None, dev_end: pd.Timestamp = DEV_END) -> dict:
    """mask: boolean Series over f's rows marking signal days (decided at close)."""
    ctrl = ctrl if ctrl is not None else control_means(f, out, rule)
    sel = mask & f["in_universe"] & out[f"{rule}__entered"]
    t = pd.DataFrame({"symbol": f["symbol"], "date": f["date"], "liq_b": f["liq_b"],
                      "vol_b": f["vol_b"], "net": out[f"{rule}__net"],
                      "outcome": out[f"{rule}__outcome"], "days": out[f"{rule}__days"]})[sel]
    if t.empty:
        return {"n": 0}
    c = ctrl[ctrl["size"] >= 5]["mean"].rename("ctrl")
    t = t.join(c, on=["date", "liq_b", "vol_b"]).dropna(subset=["ctrl"])
    t["diff"] = t["net"] - t["ctrl"]

    def block(x: pd.DataFrame) -> dict:
        if len(x) == 0:
            return {"n": 0}
        per_date = x.groupby("date")["diff"].mean()
        nd = len(per_date)
        se = per_date.std(ddof=1) / np.sqrt(nd) if nd > 1 else np.nan
        return {"n": len(x), "dates": nd, "win": (x["net"] > 0).mean(),
                "tgt": x["outcome"].isin(["target", "gap_target"]).mean(),
                "mean_net": x["net"].mean(), "ctrl_net": x["ctrl"].mean(),
                "edge": x["diff"].mean(), "t": per_date.mean() / se if se and se > 0 else np.nan,
                "days": x["days"].mean()}

    res = block(t)
    res["dev"] = block(t[t["date"] <= dev_end])
    res["hold"] = block(t[t["date"] > dev_end])
    yr = t.groupby(t["date"].dt.year)["diff"].agg(["mean", "size"])
    yr = yr[yr["size"] >= 15]
    res["years_pos"] = f"{int((yr['mean'] > 0).sum())}/{len(yr)}"
    res["by_year"] = yr["mean"].round(4).to_dict()
    res["trades"] = t
    return res


def row(name: str, rule: str, r: dict) -> dict:
    """Flatten an evaluate() result for a summary table."""
    if r.get("n", 0) == 0:
        return {"signal": name, "rule": rule, "n": 0}
    d, h = r["dev"], r["hold"]
    return {"signal": name, "rule": rule, "n": r["n"], "dates": r["dates"],
            "win": r["win"], "mean_net": r["mean_net"], "ctrl_net": r["ctrl_net"],
            "edge": r["edge"], "t": r["t"], "yrs+": r["years_pos"],
            "dev_n": d.get("n", 0), "dev_edge": d.get("edge", np.nan), "dev_t": d.get("t", np.nan),
            "hold_n": h.get("n", 0), "hold_edge": h.get("edge", np.nan), "hold_t": h.get("t", np.nan)}
