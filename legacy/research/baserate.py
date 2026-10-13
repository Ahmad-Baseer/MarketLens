"""
Multi Beggar Finder — Stage 2: measure the BASE RATE.

Before any signal is worth anything we need to know what a coin flip looks
like. Starting from a random eligible day, over the next 60 trading days:

    P(touch +10%)                 how often the target is reachable at all
    P(+10% before -8%)            the number that actually matters
    P(close day 60 >= +10%)
    MFE / MAE                     how far it ran for / against you

Split by calendar YEAR, because 2021-2026 contains a historic PSX bull run and
a strategy that only works in one year is not a strategy. Also split by PRICE
BUCKET, which settles empirically whether cheap stocks really do move in
bigger percentage steps or whether that was just intuition.

Decision logic runs on the PRICE-ONLY series (px_*) — what the chart showed,
which is what a target or stop would actually have filled against. Total
return (tr_*) is reported alongside so a dividend landing inside the window
shows up as extra, never as the reason a candidate scored well.

Entry is the NEXT bar's open after the signal bar. No same-bar fills.
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
OUT.mkdir(parents=True, exist_ok=True)

HORIZON = 60             # trading days ~ 3 calendar months
TARGET = 0.10
STOP = -0.08

# eligibility — no price cap (returns are percentages; price level is a
# hypothesis to test, not a filter to impose)
MIN_TRADED_FRAC = 0.60       # traded on >=60% of the last 60 sessions
MIN_TURNOVER = 300_000       # Rs median daily turnover over trailing 20d
MIN_PRICE = 1.00             # below Rs 1 the tick size itself is ~10% of price

# round-trip friction on a Rs 30,000 ticket: commission + CDC/SECP + spread.
# Deliberately conservative — thin PSX names cost more than the schedule says.
FRICTION = 0.012


def build(px: pd.DataFrame) -> pd.DataFrame:
    cal = np.sort(px["date"].unique())
    cal_idx = pd.Series(np.arange(len(cal)), index=cal)
    px = px.copy()
    px["t"] = px["date"].map(cal_idx).astype("int32")
    print(f"calendar: {len(cal):,} sessions "
          f"{pd.Timestamp(cal[0]).date()} -> {pd.Timestamp(cal[-1]).date()}")
    return px, pd.DatetimeIndex(cal)


def _first_true(win: np.ndarray) -> np.ndarray:
    """index of first True per row, or -1 if none."""
    any_ = win.any(axis=1)
    idx = win.argmax(axis=1)
    return np.where(any_, idx, -1)


def forward_stats(px: pd.DataFrame) -> pd.DataFrame:
    from numpy.lib.stride_tricks import sliding_window_view as swv

    out = []
    for sym, g in px.groupby("symbol", sort=False):
        g = g.sort_values("t")
        if len(g) < HORIZON + 30:
            continue
        t = g["t"].to_numpy()
        # reindex onto the contiguous session range so a symbol that stops
        # trading for 3 weeks does not get 3 weeks of free forward window
        full = np.arange(t[0], t[-1] + 1)
        gi = g.set_index("t")
        o = gi["px_open"].reindex(full).ffill().to_numpy(float)
        h = gi["px_high"].reindex(full).ffill().to_numpy(float)
        l = gi["px_low"].reindex(full).ffill().to_numpy(float)
        c = gi["px_close"].reindex(full).ffill().to_numpy(float)
        trc = gi["tr_close"].reindex(full).ffill().to_numpy(float)
        turn = gi["turnover"].reindex(full).fillna(0).to_numpy(float)
        traded = gi["traded"].reindex(full).fillna(0).to_numpy(float)
        n = len(full)
        if n < HORIZON + 2:
            continue

        traded_frac = pd.Series(traded).rolling(HORIZON, min_periods=20).mean().to_numpy()
        med_turn = pd.Series(turn).rolling(20, min_periods=10).median().to_numpy()

        # entry = next bar open; forward window = bars i+1 .. i+HORIZON
        m = n - HORIZON - 1                     # usable signal bars
        if m <= 0:
            continue
        entry = o[1:m + 1]
        Wh = swv(h, HORIZON)[1:m + 1]           # (m, HORIZON)
        Wl = swv(l, HORIZON)[1:m + 1]
        e = entry[:, None]
        with np.errstate(divide="ignore", invalid="ignore"):
            hit_up = _first_true(Wh >= e * (1 + TARGET))
            hit_dn = _first_true(Wl <= e * (1 + STOP))
            mfe = Wh.max(axis=1) / entry - 1.0
            mae = Wl.min(axis=1) / entry - 1.0
            ret60 = c[HORIZON + 1:HORIZON + 1 + m] / entry - 1.0
            tr60 = trc[HORIZON + 1:HORIZON + 1 + m] / (trc[1:m + 1]) - 1.0

        out.append(pd.DataFrame({
            "symbol": sym,
            "t": full[:m],                       # signal bar
            "close": c[:m],
            "entry": entry,
            "traded_frac": traded_frac[:m],
            "med_turnover": med_turn[:m],
            "hit_up": hit_up,
            "hit_dn": hit_dn,
            "mfe": mfe,
            "mae": mae,
            "ret60": ret60,
            "tr_ret60": tr60,
        }))
    return pd.concat(out, ignore_index=True)


def outcomes(g: pd.DataFrame) -> pd.Series:
    u = g["hit_up"] >= 0
    d = g["hit_dn"] >= 0
    fu = u & (~d | (g["hit_up"] < g["hit_dn"]))
    # mechanical rule: +10% target, -8% stop, else exit at close of day 60.
    # When both are touched in the same window we cannot tell from daily bars
    # which came first if they hit on the SAME bar -> charge the stop (pessimistic).
    same_bar = u & d & (g["hit_up"] == g["hit_dn"])
    win = fu & ~same_bar
    gross = np.where(win, TARGET, np.where(d, STOP, g["ret60"]))
    return pd.Series({
        "n_obs": len(g),
        "n_syms": g["symbol"].nunique(),
        "P_touch_+10": u.mean(),
        "P_+10_first": win.mean(),
        "P_stop_first": (d & ~win).mean(),
        "P_close60_>=+10": (g["ret60"] >= TARGET).mean(),
        "mean_ret60": g["ret60"].mean(),
        "med_ret60": g["ret60"].median(),
        "gross_exp": gross.mean(),
        "net_exp": gross.mean() - FRICTION,
        "mean_MFE": g["mfe"].mean(),
        "mean_MAE": g["mae"].mean(),
        "div_kick": (g["tr_ret60"] - g["ret60"]).mean(),
        "med_days_to_+10": g.loc[u, "hit_up"].median(),
    })


def main():
    px = pd.read_parquet(WORK / "prices.parquet")
    px, cal = build(px)
    print("computing forward excursions ...", flush=True)
    fs = forward_stats(px)
    print(f"  {len(fs):,} symbol-bars")

    fs["date"] = cal[fs["t"].to_numpy()]
    fs["year"] = fs["date"].dt.year
    elig = (
        (fs["close"] >= MIN_PRICE)
        & (fs["traded_frac"] >= MIN_TRADED_FRAC)
        & (fs["med_turnover"] >= MIN_TURNOVER)
        & fs["ret60"].notna()
        & np.isfinite(fs["ret60"])
    )
    sub = fs[elig].copy()
    print(f"  {len(sub):,} eligible bars ({elig.mean():.1%} of all) "
          f"on {sub['symbol'].nunique()} symbols")

    sub["price_bkt"] = pd.cut(
        sub["close"], [0, 5, 10, 20, 30, 50, 100, 300, np.inf],
        labels=["<5", "5-10", "10-20", "20-30", "30-50", "50-100", "100-300", "300+"])

    pd.set_option("display.width", 250)
    pd.set_option("display.float_format", lambda v: f"{v:,.3f}")

    print("\n" + "=" * 110)
    print(f"BASE RATE — all PSX, {HORIZON}-trading-day horizon, "
          f"target {TARGET:+.0%} / stop {STOP:+.0%}, entry next open")
    print(f"eligibility: price >= Rs {MIN_PRICE}, traded >= {MIN_TRADED_FRAC:.0%} of last "
          f"{HORIZON} sessions, median 20d turnover >= Rs {MIN_TURNOVER:,}")
    print(f"friction charged: {FRICTION:.1%} round trip")
    print("=" * 110)

    by_year = sub.groupby("year").apply(outcomes, include_groups=False)
    allrow = outcomes(sub).to_frame("ALL").T
    res_y = pd.concat([by_year, allrow])
    print("\n--- BY YEAR ---")
    print(res_y.to_string())

    res_p = sub.groupby("price_bkt", observed=True).apply(outcomes, include_groups=False)
    print("\n--- BY PRICE BUCKET (does 'cheap' actually move more in %?) ---")
    print(res_p.to_string())

    res_y.to_csv(OUT / "base_rate_by_year.csv")
    res_p.to_csv(OUT / "base_rate_by_price.csv")
    sub.to_parquet(WORK / "eligible_bars.parquet", index=False)
    print(f"\nwrote {OUT}/base_rate_by_year.csv, base_rate_by_price.csv")
    print(f"wrote {WORK}/eligible_bars.parquet")


if __name__ == "__main__":
    main()
