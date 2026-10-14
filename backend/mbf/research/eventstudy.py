"""Variable-window event trades with a same-window matched control.

For trades whose holding period differs per event (e.g. "buy near the close
after a dividend announcement, sell at the ex-date's opening auction"), the
control is the average universe stock in the same liquidity bucket over the
EXACT same window, so market moves and the overnight effect cancel out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mbf.research.outcomes import DEFAULT_COST, DIV_TAX


def _panel(f: pd.DataFrame):
    s = pd.DatetimeIndex(np.sort(f["date"].unique()))
    pos = pd.Series(np.arange(len(s)), index=s)
    wide = {c: f.pivot(index="date", columns="symbol", values=c).reindex(s)
            for c in ("adj_open", "adj_close", "traded", "factor", "in_universe", "to_rank")}
    return s, pos, wide


def trades(f: pd.DataFrame, ev: pd.DataFrame, entry: str = "close", exit: str = "open",
           cost: float = DEFAULT_COST, div_tax: float = DIV_TAX, panel=None) -> pd.DataFrame:
    """ev: columns symbol, entry_idx, exit_idx (session indices). Entry at the close (or
    open) of entry_idx, exit at the open (or close) of exit_idx."""
    s, pos, w = panel or _panel(f)
    O, C, T, F = (w[c].to_numpy(float) for c in ("adj_open", "adj_close", "traded", "factor"))
    U, LQ = w["in_universe"].fillna(False).to_numpy(bool), w["to_rank"].to_numpy(float)
    cols = {sym: i for i, sym in enumerate(w["adj_close"].columns)}
    rows = []
    for e in ev.itertuples():
        j = cols.get(e.symbol)
        a, b = int(e.entry_idx), int(e.exit_idx)
        if j is None or not (0 <= a < b < len(s)):
            continue
        px_in = C[a] if entry == "close" else O[a]
        px_out = O[b] if exit == "open" else C[b]
        if not (T[a, j] == 1 and T[b, j] == 1 and np.isfinite(px_in[j]) and np.isfinite(px_out[j])):
            continue
        # dividends collected on ex-dates in (a, b] (exit at an ex-date's open still collects)
        fac = F[a + 1:b + 1]
        cash = np.where((fac < 1) & (fac >= 0.85), 1 - fac, 0.0).sum(axis=0)
        r = px_out / px_in - 1 - div_tax * cash - cost
        # control: same window, universe at entry, same liquidity bucket, traded both ends
        lq = LQ[a, j]
        bucket = (LQ[a] <= 50) if lq <= 50 else ((LQ[a] > 50) & (LQ[a] <= 100)) if lq <= 100 else (LQ[a] > 100)
        ok = U[a] & bucket & (T[a] == 1) & (T[b] == 1) & np.isfinite(r)
        ok[j] = False
        ctrl = np.nanmean(r[ok]) if ok.sum() >= 5 else np.nan
        rows.append({"symbol": e.symbol, "date": s[a], "exit_date": s[b], "nights": b - a,
                     "net": r[j], "ctrl": ctrl, **{k: getattr(e, k) for k in ev.columns
                                                   if k not in ("symbol", "entry_idx", "exit_idx")}})
    t = pd.DataFrame(rows)
    if not t.empty:
        t["diff"] = t["net"] - t["ctrl"]
    return t


def summarize(t: pd.DataFrame, name: str, dev_end: str = "2022-12-31") -> dict:
    if t.empty:
        return {"signal": name, "n": 0}
    t = t.dropna(subset=["ctrl"])

    def blk(x):
        if len(x) < 2:
            return {"n": len(x)}
        pdm = x.groupby("date")["diff"].mean()
        se = pdm.std(ddof=1) / np.sqrt(len(pdm))
        return {"n": len(x), "net": x["net"].mean(), "edge": x["diff"].mean(),
                "t": pdm.mean() / se if se > 0 else np.nan, "win": (x["net"] > 0).mean()}

    a, d, h = blk(t), blk(t[t["date"] <= dev_end]), blk(t[t["date"] > dev_end])
    yr = t.groupby(t["date"].dt.year)["diff"].mean()
    return {"signal": name, "n": a["n"], "nights": t["nights"].mean(), "win": a.get("win"),
            "mean_net": a.get("net"), "edge": a.get("edge"), "t": a.get("t"),
            "yrs+": f"{int((yr > 0).sum())}/{len(yr)}",
            "dev_edge": d.get("edge"), "dev_t": d.get("t"), "hold_n": h.get("n"),
            "hold_net": h.get("net"), "hold_edge": h.get("edge"), "hold_t": h.get("t")}
