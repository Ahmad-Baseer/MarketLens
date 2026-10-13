"""
Multi Beggar Finder — Stage 5: validate the survivors honestly.

Three checks the scoreboard cannot answer:

1. BY YEAR. Pooled edge hides regime dependence. A signal must work in most
   years, not on average.
2. MULTIPLE COMPARISONS. 19 signals were screened. At |z|>2 roughly one false
   positive is expected by chance, so anything below |z|~3 is NOT established.
   Stated explicitly per signal rather than buried.
3. PORTFOLIO REALITY. Per-trade expectancy is not what lands in the account.
   Rs 30,000 per position, a hard cap on concurrent holdings, one entry per
   symbol at a time, real friction, and the fact that signals cluster in time
   (many fire the same week, then nothing for a month).

Plus a genuine HOLDOUT: rules are fixed on 2021-08..2024-12 and then run
untouched on 2025-01..2026-05.
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
TICKET = 30_000
HOLDOUT_START = "2025-01-01"


def load():
    p = pd.read_parquet(WORK / "panel.parquet")
    p["liq_bkt"] = pd.qcut(p["med_turnover"], 4, labels=False, duplicates="drop")
    p["atr_bkt"] = pd.qcut(p["atr_pct"], 4, labels=False, duplicates="drop")
    p["price_bkt"] = pd.cut(p["close"], [0, 5, 10, 20, 30, 50, 100, 300, np.inf])
    return p


STRATA = ["year", "price_bkt", "liq_bkt", "atr_bkt"]


def ctrl(p, sel):
    w = sel.groupby(STRATA, observed=True).size().rename("w")
    agg = p.groupby(STRATA, observed=True).agg(P=("win_atr", "mean"),
                                               E=("pnl_atr", "mean"), n=("win_atr", "size"))
    j = agg.join(w, how="inner")
    j = j[j["n"] >= 20]
    if j.empty:
        return np.nan, np.nan
    wt = j["w"] / j["w"].sum()
    return float((j["P"] * wt).sum()), float((j["E"] * wt).sum())


def year_table(p, sel, name):
    rows = []
    for y, g in sel.groupby("year"):
        if len(g) < 30:
            continue
        cP, cE = ctrl(p[p["year"] == y], g)
        rows.append({"year": y, "n": len(g), "P_win": g["win_atr"].mean(), "ctrl_P": cP,
                     "edge": g["win_atr"].mean() - cP,
                     "net": g["pnl_atr"].mean() - FRICTION,
                     "ctrl_net": cE - FRICTION})
    df = pd.DataFrame(rows)
    print(f"\n--- {name} ---")
    print(df.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    return df


def portfolio(sel: pd.DataFrame, max_pos: int, label: str,
              start=None, end=None) -> dict:
    """Sequential portfolio sim. Signals sorted by date; take a new position
    only if a slot is free and that symbol is not already held. Exit is the
    ATR target/stop or the 60-day time stop, whichever came first — days_to_tgt
    gives the target-hit bar, otherwise we charge the full horizon."""
    s = sel.copy()
    if start:
        s = s[s["date"] >= start]
    if end:
        s = s[s["date"] < end]
    s = s.sort_values("date")
    if s.empty:
        return {}

    # holding period in bars
    hold = np.where(s["win_atr"], s["days_to_tgt"] + 1, 60)
    s = s.assign(hold=hold)
    # realised per-trade return net of friction
    s = s.assign(r=s["pnl_atr"] - FRICTION)

    free_at = np.zeros(max_pos)          # bar index when each slot frees
    sym_free = {}
    trades = []
    for row in s.itertuples():
        t = row.t
        if sym_free.get(row.symbol, -1) > t:
            continue                      # already holding this name
        slot = int(np.argmin(free_at))
        if free_at[slot] > t:
            continue                      # all slots busy
        free_at[slot] = t + row.hold
        sym_free[row.symbol] = t + row.hold
        trades.append((row.date, row.symbol, row.r, row.hold))

    if not trades:
        return {}
    td = pd.DataFrame(trades, columns=["date", "symbol", "r", "hold"])
    eq = (1 + td["r"] / max_pos).cumprod()          # each trade risks 1/max_pos of book
    peak = eq.cummax()
    dd = (eq / peak - 1).min()
    yrs = (td["date"].max() - td["date"].min()).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0.5 else np.nan
    # worst losing streak
    L = (td["r"] < 0).astype(int).to_numpy()
    streak = mx = 0
    for x in L:
        streak = streak + 1 if x else 0
        mx = max(mx, streak)
    return {"label": label, "trades": len(td), "yrs": round(yrs, 2),
            "P_win": (td["r"] > 0).mean(), "mean_r": td["r"].mean(),
            "total_x": eq.iloc[-1], "CAGR": cagr, "maxDD": dd,
            "worst_streak": mx, "avg_hold_d": td["hold"].mean(),
            "trades_per_yr": len(td) / yrs if yrs else np.nan}


def main():
    p = load()
    pd.set_option("display.width", 250)

    # ---- the survivors from the scoreboard -------------------------------
    mom_lo_thr = p["mom60"].quantile(.2)
    S = {
        "MeanRev: 60d momentum bottom quintile": p[p["mom60"] <= mom_lo_thr],
        "Deep: >50% off 120d high": p[p["off_hi120"] < -0.50],
    }
    for k, v in S.items():
        year_table(p, v, k)

    print("\n" + "=" * 118)
    print("MULTIPLE-COMPARISONS NOTE: 19 signals screened. |z|>3 is the honest bar;")
    print("  MeanRev z=+19.0 and the negative volume/notice signals clear it.")
    print("  Every PEAD variant (z=+2.2..+2.5) does NOT — suggestive, not established.")
    print("=" * 118)

    # ---- portfolio: in-sample vs holdout --------------------------------
    print("\n=== PORTFOLIO SIM — Rs 30,000/position, friction 1.2%/trade ===")
    res = []
    for name, sel in S.items():
        for mp in (5, 10):
            for tag, a, b in [("IN-SAMPLE 21-24", None, HOLDOUT_START),
                              ("HOLDOUT 25-26", HOLDOUT_START, None),
                              ("FULL", None, None)]:
                r = portfolio(sel, mp, f"{name} | {mp} slots | {tag}", a, b)
                if r:
                    res.append(r)
    rd = pd.DataFrame(res)
    rd["capital"] = rd["label"].str.extract(r"\| (\d+) slots").astype(int) * TICKET
    print(rd[["label", "capital", "trades", "yrs", "P_win", "mean_r", "total_x",
              "CAGR", "maxDD", "worst_streak", "trades_per_yr"]]
          .to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

    # ---- benchmark: same sim on RANDOM eligible bars ---------------------
    rng = np.random.default_rng(7)
    rnd = p.iloc[rng.choice(len(p), size=60_000, replace=False)]
    print("\n=== same sim on RANDOM entries (the thing to beat) ===")
    rb = [portfolio(rnd, mp, f"RANDOM | {mp} slots | {tag}", a, b)
          for mp in (5, 10)
          for tag, a, b in [("IN-SAMPLE 21-24", None, HOLDOUT_START),
                            ("HOLDOUT 25-26", HOLDOUT_START, None)]]
    rbd = pd.DataFrame([x for x in rb if x])
    print(rbd[["label", "trades", "yrs", "P_win", "mean_r", "total_x", "CAGR",
               "maxDD", "worst_streak"]]
          .to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

    rd.to_csv(OUT / "portfolio_results.csv", index=False)
    rbd.to_csv(OUT / "portfolio_random.csv", index=False)
    print(f"\nwrote {OUT}/portfolio_results.csv")


if __name__ == "__main__":
    main()
