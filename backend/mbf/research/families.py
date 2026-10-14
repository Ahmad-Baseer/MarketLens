"""Signal families, defined BEFORE looking at results (pre-registered list).

`build(f)` returns {name: (mask, rules)}: the mask marks the day a signal is
decided (at that day's close); `rules` lists the trade rules to test it with
(None = the default set for price patterns). Thresholds that need a
distribution use only the trailing year — no look-ahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mbf.research import events as ev

DEFAULT_RULES = ["time1", "time3", "time5", "atr_1.5_2.0_h5", "atr_1.0_1.5_h3",
                 "C_time1_O", "C_time3_O", "C_time5_O", "C_atr_1.5_2.0_h5_O"]


def _rows(f: pd.DataFrame, keys: pd.DataFrame) -> pd.Series:
    """Mask of f rows matching (symbol, date) pairs in keys."""
    k = keys[["symbol", "date"]].drop_duplicates().assign(_hit=True)
    m = f[["symbol", "date"]].merge(k, on=["symbol", "date"], how="left")["_hit"]
    return m.fillna(False).astype(bool).set_axis(f.index)


def _trailing_quantile(events: pd.DataFrame, col: str, q: float, window_days: int = 365,
                       min_n: int = 100) -> pd.Series:
    """For each event, the q-quantile of `col` over events in the prior window."""
    e = events.sort_values("d0")
    vals, dates = e[col].to_numpy(float), e["d0"].to_numpy()
    out = np.full(len(e), np.nan)
    lo = 0
    for i in range(len(e)):
        while dates[lo] < dates[i] - np.timedelta64(window_days, "D"):
            lo += 1
        hist = vals[lo:i]
        hist = hist[np.isfinite(hist)]
        if len(hist) >= min_n:
            out[i] = np.quantile(hist, q)
    return pd.Series(out, index=e.index).reindex(events.index)


def _xs_rank(f: pd.DataFrame, col: str) -> pd.Series:
    """Cross-sectional percentile within each day's universe."""
    u = f["in_universe"]
    r = pd.Series(np.nan, index=f.index)
    r[u] = f.loc[u].groupby("date")[col].rank(pct=True)
    return r


def _at_offset(events: pd.DataFrame, s: pd.DatetimeIndex, idx_col: str, k: int,
               known_col: str) -> pd.DataFrame:
    """Signal day = k+1 sessions before the event, only if the event was known by then."""
    p = events.copy()
    p["sig_idx"] = p[idx_col] - k - 1
    p = p[(p["sig_idx"] >= 0) & (p[known_col] <= p["sig_idx"])]
    p["date"] = s[p["sig_idx"].astype(int).to_numpy()]
    return p


def build(f: pd.DataFrame) -> dict[str, tuple[pd.Series, list[str] | None]]:
    s = ev._sessions(f)
    E = ev.earnings(f)
    E["hi"] = _trailing_quantile(E, "surprise", 0.8)
    E["lo"] = _trailing_quantile(E, "surprise", 0.2)
    beat = E[E["surprise"] >= E["hi"]]
    miss = E[E["surprise"] <= E["lo"]]
    clean = beat[(beat["eps"] > 0) & (beat["sales_g"] > 0) & ~beat["oneoff_flag"]]
    d0 = lambda x: x.rename(columns={"d0": "date"})

    sig: dict[str, tuple[pd.Series, list[str] | None]] = {}
    sig["earn_beat"] = (_rows(f, d0(beat)), None)
    sig["earn_beat_clean"] = (_rows(f, d0(clean)), None)
    sig["earn_miss (control)"] = (_rows(f, d0(miss)), None)
    sig["earn_turnaround"] = (_rows(f, d0(E[E["turnaround"]])), None)

    # pre-results run-up: decide k+1 sessions before a scheduled results meeting,
    # buy near the next close, sell at the meeting day's opening auction
    R = ev.results_meetings(f, E)
    for k in (3, 5):
        p = _at_offset(R, s, "x_idx", k, "notice_idx")
        sig[f"pre_results_k{k}"] = (_rows(f, p), [f"C_time{k}_O"])
        sig[f"pre_results_k{k}_last_beat"] = (_rows(f, p[p["prev_delta"] > 0]), [f"C_time{k}_O"])

    # dividend run-up: k sessions before the ex-date (only once the payout is announced).
    #   preex:   buy near close of X-k, sell at the open of X-1 (never hold into the ex-date)
    #   capture: buy near close of X-k, sell at the ex-date's opening auction (collects the
    #            dividend, 15% withholding deducted)
    P = ev.payouts(f)
    close = f.set_index(["symbol", "date"])["close"]
    for k in (3, 5, 7):
        p = _at_offset(P, s, "x_idx", k, "ann_idx")
        p["yld"] = p["div_rs"] / close.reindex(list(zip(p["symbol"], p["date"]))).to_numpy()
        div2 = p[(p["yld"] >= 0.02) & (p["bonus_r"] == 0)]
        div4 = p[(p["yld"] >= 0.04) & (p["bonus_r"] == 0)]
        sig[f"div_run_k{k}_preex"] = (_rows(f, div2), [f"C_time{k - 1}_O"])
        sig[f"div_run_k{k}_capture"] = (_rows(f, div2), [f"C_time{k}_O"])
        sig[f"div_run_k{k}_yld4_preex"] = (_rows(f, div4), [f"C_time{k - 1}_O"])
        sig[f"bonus_run_k{k}_preex"] = (_rows(f, p[p["bonus_r"] >= 0.10]), [f"C_time{k - 1}_O"])
    # the original open-entry version, for comparison with the first scoreboard
    p5 = _at_offset(P, s, "x_idx", 5, "ann_idx")
    p5["yld"] = p5["div_rs"] / close.reindex(list(zip(p5["symbol"], p5["date"]))).to_numpy()
    sig["div_run_k5_open_entry"] = (_rows(f, p5[(p5["yld"] >= 0.02) & (p5["bonus_r"] == 0)]), ["time5"])

    # price patterns (modern era, need 200-day history)
    r5, r20 = _xs_rank(f, "r5"), _xs_rank(f, "r20")
    up = (f["dma200"] > 0) & f["ma50_rising"]
    pit = ev.pit_fundamentals(f, E)
    good = ((pit["last_eps_annual"] > 0) & (pit["last_eps_delta"] >= 0)
            & (pit["days_since_results"] <= 200) & ~pit["last_oneoff"].fillna(False).astype(bool))
    sig["reversal_r5_bottom_decile"] = (r5 <= 0.10, None)
    sig["reversal_r5_bottom_decile + fundamentals"] = ((r5 <= 0.10) & good, None)
    sig["pullback_uptrend_rsi2<10"] = (up & (f["rsi2"] < 10), None)
    sig["pullback_uptrend_rsi2<10 + fundamentals"] = (up & (f["rsi2"] < 10) & good, None)
    sig["breakout_contraction"] = ((f["adj_close"] > f["hi20_prev"]) & (f["rng10_vs60"] < 0.8)
                                   & f["vol_ratio"].between(1.2, 3), None)
    sig["deep_value_rebound"] = ((f["off_hi120"] < -0.5) & (f["close_loc"] > 0.7) & (f["r1"] > 0)
                                 & (f["vol_ratio"] > 1.5), None)
    # expected NEGATIVE (legacy findings at 60d): sanity checks for the harness
    sig["momentum_r20_top_decile (control)"] = (r20 >= 0.90, None)
    sig["volume_spike_>3x (control)"] = (f["vol_ratio"] > 3, None)
    sig["unusual_movement_letter (control)"] = (_rows(f, d0(ev.unusual_movement(f))), None)
    return sig
