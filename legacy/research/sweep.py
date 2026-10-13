"""
Multi Beggar Finder — Stage 2b: exit-geometry sweep.

The first base-rate run said the -8% stop / +10% target rule loses ~1.0% per
trade on random entries, while mean MAE was -15.0% and mean MFE +26.8%. That
is the signature of a stop sitting INSIDE the noise: trades that would have
worked get stopped out on the way.

So before testing any signal, find the exit geometry a signal would even be
worth pairing with. Sweeps:
  * fixed  stops -6%..-25%  x targets +8%..+30%
  * ATR-scaled stops/targets (k * ATR20/price), which adapts to the fact that
    a Rs 4 stock and a Rs 400 stock have very different normal daily ranges

IMPORTANT COVERAGE NOTE: AKD's /daily endpoint only returns deep history for a
handful of symbols (2012-2020 has 3-33 symbols per year vs 285-457 for 2021+).
Pre-2021 rows are therefore a biased subsample of survivors and are EXCLUDED.
All results below are 2021-08-23 onward.
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
from numpy.lib.stride_tricks import sliding_window_view as swv

WORK = _BASE / "work"
OUT = _BASE / "out"

HORIZON = 60
FRICTION = 0.012
START = "2021-08-23"

MIN_TRADED_FRAC = 0.60
MIN_TURNOVER = 300_000
MIN_PRICE = 1.00

FIXED_STOPS = [-0.06, -0.08, -0.10, -0.12, -0.15, -0.20, -0.25]
FIXED_TGTS = [0.08, 0.10, 0.12, 0.15, 0.20, 0.30]
ATR_STOPS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
ATR_TGTS = [1.5, 2.0, 3.0, 4.0, 5.0, 6.0]


def collect():
    px = pd.read_parquet(WORK / "prices.parquet")
    cal = np.sort(px["date"].unique())
    cal_idx = pd.Series(np.arange(len(cal)), index=cal)
    px["t"] = px["date"].map(cal_idx).astype("int32")
    cal = pd.DatetimeIndex(cal)
    t_start = int(cal_idx[cal[cal >= START][0]])

    recs = []
    for sym, g in px.groupby("symbol", sort=False):
        g = g.sort_values("t")
        if len(g) < HORIZON + 40:
            continue
        t = g["t"].to_numpy()
        full = np.arange(t[0], t[-1] + 1)
        gi = g.set_index("t")
        o = gi["px_open"].reindex(full).ffill().to_numpy(float)
        h = gi["px_high"].reindex(full).ffill().to_numpy(float)
        l = gi["px_low"].reindex(full).ffill().to_numpy(float)
        c = gi["px_close"].reindex(full).ffill().to_numpy(float)
        turn = gi["turnover"].reindex(full).fillna(0).to_numpy(float)
        traded = gi["traded"].reindex(full).fillna(0).to_numpy(float)
        n = len(full)
        m = n - HORIZON - 1
        if m <= 0:
            continue

        # true range / ATR20 as a fraction of price, trailing only
        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        atr = pd.Series(tr).rolling(20, min_periods=10).mean().to_numpy()
        atr_pct = np.divide(atr, c, out=np.full_like(atr, np.nan), where=c > 0)

        tf = pd.Series(traded).rolling(HORIZON, min_periods=20).mean().to_numpy()
        mt = pd.Series(turn).rolling(20, min_periods=10).median().to_numpy()

        entry = o[1:m + 1]
        Wh = swv(h, HORIZON)[1:m + 1]
        Wl = swv(l, HORIZON)[1:m + 1]
        with np.errstate(divide="ignore", invalid="ignore"):
            up = Wh / entry[:, None] - 1.0      # running favourable excursion path
            dn = Wl / entry[:, None] - 1.0
            ret60 = c[HORIZON + 1:HORIZON + 1 + m] / entry - 1.0

        keep = (
            (full[:m] >= t_start)
            & (c[:m] >= MIN_PRICE)
            & (tf[:m] >= MIN_TRADED_FRAC)
            & (mt[:m] >= MIN_TURNOVER)
            & np.isfinite(ret60)
            & np.isfinite(atr_pct[:m])
        )
        if not keep.any():
            continue
        recs.append((sym, full[:m][keep], up[keep], dn[keep],
                     ret60[keep], atr_pct[:m][keep]))
    return recs, cal


def evaluate(recs, tgt_arr, stop_arr):
    """tgt_arr/stop_arr are per-observation thresholds (fractions)."""
    wins = losses = timeouts = 0
    pnl_sum = 0.0
    n = 0
    off = 0
    for _sym, ts, up, dn, ret60, _atr in recs:
        k = len(ts)
        T = tgt_arr[off:off + k][:, None]
        S = stop_arr[off:off + k][:, None]
        off += k
        hu = (up >= T)
        hd = (dn <= S)
        au, ad = hu.any(1), hd.any(1)
        iu = np.where(au, hu.argmax(1), 1 << 30)
        idn = np.where(ad, hd.argmax(1), 1 << 30)
        win = au & (iu < idn)                  # strict: same-bar ties -> loss
        loss = ad & ~win
        pnl = np.where(win, T[:, 0], np.where(loss, S[:, 0], ret60))
        wins += int(win.sum()); losses += int(loss.sum())
        timeouts += int((~win & ~loss).sum())
        pnl_sum += float(pnl.sum()); n += k
    return dict(n=n, P_win=wins / n, P_loss=losses / n, P_timeout=timeouts / n,
                gross=pnl_sum / n, net=pnl_sum / n - FRICTION)


def main():
    print("collecting excursion paths (2021-08-23 onward) ...", flush=True)
    recs, cal = collect()
    N = sum(len(r[1]) for r in recs)
    print(f"  {N:,} eligible bars on {len(recs)} symbols")
    atr = np.concatenate([r[5] for r in recs])
    print(f"  ATR20/price: median {np.median(atr):.3%}  p10 {np.percentile(atr,10):.3%}  "
          f"p90 {np.percentile(atr,90):.3%}")

    pd.set_option("display.width", 250)

    rows = []
    for s in FIXED_STOPS:
        for tg in FIXED_TGTS:
            r = evaluate(recs, np.full(N, tg), np.full(N, s))
            rows.append({"stop": f"{s:+.0%}", "target": f"{tg:+.0%}", **r})
    fx = pd.DataFrame(rows)
    print("\n=== FIXED geometry (random entry, 2021+) — net expectancy per trade ===")
    print(fx.pivot(index="stop", columns="target", values="net")
            .reindex([f"{s:+.0%}" for s in FIXED_STOPS])
            .to_string(float_format=lambda v: f"{v:+.4f}"))
    print("\n    P(win) for the same grid:")
    print(fx.pivot(index="stop", columns="target", values="P_win")
            .reindex([f"{s:+.0%}" for s in FIXED_STOPS])
            .to_string(float_format=lambda v: f"{v:.3f}"))

    rows = []
    for ks in ATR_STOPS:
        for kt in ATR_TGTS:
            r = evaluate(recs, kt * atr, -ks * atr)
            rows.append({"stop_atr": f"{ks}x", "tgt_atr": f"{kt}x", **r})
    ar = pd.DataFrame(rows)
    print("\n=== ATR-SCALED geometry (stop = -k*ATR20, target = +m*ATR20) ===")
    print(ar.pivot(index="stop_atr", columns="tgt_atr", values="net")
            .reindex([f"{k}x" for k in ATR_STOPS])
            .to_string(float_format=lambda v: f"{v:+.4f}"))
    print("\n    P(win) for the same grid:")
    print(ar.pivot(index="stop_atr", columns="tgt_atr", values="P_win")
            .reindex([f"{k}x" for k in ATR_STOPS])
            .to_string(float_format=lambda v: f"{v:.3f}"))

    fx.to_csv(OUT / "geometry_fixed.csv", index=False)
    ar.to_csv(OUT / "geometry_atr.csv", index=False)
    best = pd.concat([fx.assign(kind="fixed"), ar.assign(kind="atr")]).nlargest(8, "net")
    print("\n=== best 8 overall (still RANDOM entry — this is the bar to beat) ===")
    print(best[["kind", "stop", "target", "stop_atr", "tgt_atr", "n",
                "P_win", "P_loss", "P_timeout", "gross", "net"]].to_string(index=False))
    print(f"\nwrote {OUT}/geometry_fixed.csv, geometry_atr.csv")


if __name__ == "__main__":
    main()
