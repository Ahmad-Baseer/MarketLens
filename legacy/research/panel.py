"""
Multi Beggar Finder — Stage 3: the definitive bar-level panel.

One row per (symbol, signal bar) from 2021-08-23 onward, carrying:
  * eligibility / liquidity context (trailing only)
  * trailing features a signal may use (momentum, volume expansion, ATR)
  * forward outcomes under the PRIMARY geometry

PRIMARY GEOMETRY: stop = -2.5 x ATR20, target = +3.0 x ATR20, time stop 60d.
Chosen because random entry there nets ~0.0% after 1.2% friction (see
out/geometry_atr.csv), so any signal's edge reads as a clean difference rather
than being hidden inside 2021-2026 market drift. The fixed -8%/+10% geometry is
ALSO computed, because that is the intuitive rule and it is useful to show what
it costs (random entry: -0.95%/trade).

Everything trailing is strictly backward-looking. Entry is the next bar's open.
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

HORIZON = 60
START = "2021-08-23"
FRICTION = 0.012
K_STOP, K_TGT = 2.5, 3.0          # primary, in ATR20 units
FIX_STOP, FIX_TGT = -0.08, 0.10   # the intuitive rule, for comparison

MIN_TRADED_FRAC = 0.60
MIN_TURNOVER = 300_000
MIN_PRICE = 1.00


def _first(mask):
    a = mask.any(1)
    return np.where(a, mask.argmax(1), 1 << 30)


def build() -> pd.DataFrame:
    px = pd.read_parquet(WORK / "prices.parquet")
    cal = np.sort(px["date"].unique())
    cal_idx = pd.Series(np.arange(len(cal)), index=cal)
    px["t"] = px["date"].map(cal_idx).astype("int32")
    cal = pd.DatetimeIndex(cal)
    t0 = int(cal_idx[cal[cal >= START][0]])

    out = []
    for sym, g in px.groupby("symbol", sort=False):
        g = g.sort_values("t")
        if len(g) < HORIZON + 140:
            continue
        t = g["t"].to_numpy()
        full = np.arange(t[0], t[-1] + 1)
        gi = g.set_index("t")
        o = gi["px_open"].reindex(full).ffill().to_numpy(float)
        h = gi["px_high"].reindex(full).ffill().to_numpy(float)
        l = gi["px_low"].reindex(full).ffill().to_numpy(float)
        c = gi["px_close"].reindex(full).ffill().to_numpy(float)
        trc = gi["tr_close"].reindex(full).ffill().to_numpy(float)
        v = gi["volume"].reindex(full).fillna(0).to_numpy(float)
        turn = gi["turnover"].reindex(full).fillna(0).to_numpy(float)
        traded = gi["traded"].reindex(full).fillna(0).to_numpy(float)
        n = len(full)
        m = n - HORIZON - 1
        if m <= 0:
            continue

        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        atr = pd.Series(tr).rolling(20, min_periods=10).mean().to_numpy()
        atr_pct = np.divide(atr, c, out=np.full_like(atr, np.nan), where=c > 0)

        S = pd.Series(c)
        mom20 = (S / S.shift(20) - 1).to_numpy()
        mom60 = (S / S.shift(60) - 1).to_numpy()
        mom120 = (S / S.shift(120) - 1).to_numpy()
        # distance below the trailing 120d high — "dead chart" vs "extended"
        hi120 = S.rolling(120, min_periods=60).max().to_numpy()
        off_hi = np.divide(c, hi120, out=np.full_like(c, np.nan), where=hi120 > 0) - 1.0
        # volume expansion: 20d mean vs 100d mean
        V = pd.Series(v)
        vexp = (V.rolling(20, min_periods=10).mean()
                / V.rolling(100, min_periods=50).mean().replace(0, np.nan)).to_numpy()
        # realised vol of daily returns, 60d
        rets = S.pct_change()
        vol60 = rets.rolling(60, min_periods=30).std().to_numpy()

        tf = pd.Series(traded).rolling(HORIZON, min_periods=20).mean().to_numpy()
        mt = pd.Series(turn).rolling(20, min_periods=10).median().to_numpy()

        entry = o[1:m + 1]
        Wh = swv(h, HORIZON)[1:m + 1]
        Wl = swv(l, HORIZON)[1:m + 1]
        with np.errstate(divide="ignore", invalid="ignore"):
            up = Wh / entry[:, None] - 1.0
            dn = Wl / entry[:, None] - 1.0
            ret60 = c[HORIZON + 1:HORIZON + 1 + m] / entry - 1.0
            tr60 = trc[HORIZON + 1:HORIZON + 1 + m] / trc[1:m + 1] - 1.0
            mfe = up.max(1)
            mae = dn.min(1)

            ap = atr_pct[:m]
            tgt_a = K_TGT * ap
            stp_a = -K_STOP * ap
            iu = _first(up >= tgt_a[:, None])
            idn = _first(dn <= stp_a[:, None])
            win_a = (iu < idn) & (iu < (1 << 30))
            loss_a = (idn <= iu) & (idn < (1 << 30))
            pnl_a = np.where(win_a, tgt_a, np.where(loss_a, stp_a, ret60))

            iu_f = _first(up >= FIX_TGT)
            idn_f = _first(dn <= FIX_STOP)
            win_f = (iu_f < idn_f) & (iu_f < (1 << 30))
            loss_f = (idn_f <= iu_f) & (idn_f < (1 << 30))
            pnl_f = np.where(win_f, FIX_TGT, np.where(loss_f, FIX_STOP, ret60))

        keep = (
            (full[:m] >= t0) & (c[:m] >= MIN_PRICE)
            & (tf[:m] >= MIN_TRADED_FRAC) & (mt[:m] >= MIN_TURNOVER)
            & np.isfinite(ret60) & np.isfinite(ap)
        )
        if not keep.any():
            continue
        out.append(pd.DataFrame({
            "symbol": sym, "t": full[:m][keep], "close": c[:m][keep],
            "entry": entry[keep], "atr_pct": ap[keep],
            "traded_frac": tf[:m][keep], "med_turnover": mt[:m][keep],
            "mom20": mom20[:m][keep], "mom60": mom60[:m][keep],
            "mom120": mom120[:m][keep], "off_hi120": off_hi[:m][keep],
            "vol_exp": vexp[:m][keep], "vol60": vol60[:m][keep],
            "ret60": ret60[keep], "tr_ret60": tr60[keep],
            "mfe": mfe[keep], "mae": mae[keep],
            "days_to_tgt": np.where(win_a, iu, -1)[keep],
            "win_atr": win_a[keep], "loss_atr": loss_a[keep], "pnl_atr": pnl_a[keep],
            "win_fix": win_f[keep], "loss_fix": loss_f[keep], "pnl_fix": pnl_f[keep],
        }))
    p = pd.concat(out, ignore_index=True)
    p["date"] = cal[p["t"].to_numpy()]
    p["year"] = p["date"].dt.year
    return p


def main():
    p = build()
    prof = pd.read_parquet(WORK / "profiles.parquet")
    p = p.merge(prof[["symbol", "sector_name", "active"]], on="symbol", how="left")

    # market context: cross-sectional median 60d forward return per bar date,
    # used to separate "signal works" from "market went up that quarter"
    mkt = p.groupby("date")["ret60"].median().rename("mkt_ret60")
    p = p.merge(mkt, on="date", how="left")
    p["excess60"] = p["ret60"] - p["mkt_ret60"]

    p.to_parquet(WORK / "panel.parquet", index=False)
    print(f"panel: {len(p):,} rows  {p['symbol'].nunique()} symbols  "
          f"{p['date'].min().date()} -> {p['date'].max().date()}")
    print(f"\nrandom-entry benchmark on this panel:")
    for tag, w, l, pnl in [("ATR 2.5x/3.0x", "win_atr", "loss_atr", "pnl_atr"),
                           ("fixed -8%/+10%", "win_fix", "loss_fix", "pnl_fix")]:
        print(f"  {tag:16s} P(win)={p[w].mean():.3f}  P(loss)={p[l].mean():.3f}  "
              f"gross={p[pnl].mean():+.4f}  net={p[pnl].mean()-FRICTION:+.4f}")
    print(f"\nwrote {WORK}/panel.parquet")


if __name__ == "__main__":
    main()
