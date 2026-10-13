"""Realistic trade simulation, vectorised over every symbol-day at once.

A signal decided after the close of day t is traded like this:

ENTRY (day e = t+1)
  * "open":  at t+1's opening-auction price. Stop/target are fixed as PRICES
             from t's close (that is what a signal published in the evening
             shows). Skipped if t+1 doesn't trade, is locked at the upper
             circuit, opens below the stop, or opens more than `max_chase` of
             the way to the target (never chase a gap).
  * "close": near t+1's close (PSX's close is the VWAP of the last 30 minutes,
             so this is achievable by buying through the last half hour).
             Stop/target are set from the entry price. Skipped if t+1 doesn't
             trade, is upper-locked, or has already risen more than
             `max_chase_atr` ATRs above t's close.

HOLDING
  * a gap through the stop/target exits at that day's open;
  * otherwise stop/target are checked against the day's range; if BOTH are
    touched the same day the stop is assumed first (intraday order unknown);
  * a stop on a lower-circuit-locked day can't be sold: out at the next open.

EXIT (time stop after `horizon` sessions)
  * "close": at the close of the last holding day;
  * "open":  at the opening auction of the following day. PSX's liquid stocks
             gain ~+0.28% overnight and lose ~-0.20% intraday on average (every
             year 2014-2026), so where you enter and exit matters a lot.

Prices are the dividend/bonus-adjusted series, so any dividend collected is in
the return; `div_tax` (15% withholding for ATL filers) is deducted from it.
Costs are charged per round trip.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_COST = 0.006           # round trip: brokerage+taxes ~0.4% + slippage ~0.2%
DIV_TAX = 0.15                 # withholding on cash dividends, ATL filers (30% non-filers)


@dataclass(frozen=True)
class ExitRule:
    name: str
    horizon: int                  # holding sessions (time stop)
    stop_atr: float = np.inf      # inf = no stop
    target_atr: float = np.inf    # inf = no target
    entry: str = "open"           # "open" | "close"
    exit: str = "close"           # "close" | "open" (time-stop exit)
    max_chase: float = 0.5        # open entry: skip beyond this share of the way to target
    max_chase_atr: float = 1.0    # close entry: skip if already up more than this many ATRs


def _r(name, h, s=np.inf, g=np.inf, entry="open", exit="close"):
    return name, ExitRule(name, h, s, g, entry, exit)


RULES = dict([
    _r("time1", 1), _r("time3", 3), _r("time5", 5),
    _r("atr_1.5_2.0_h5", 5, 1.5, 2.0), _r("atr_1.0_1.5_h3", 3, 1.0, 1.5),
    _r("atr_2.0_3.0_h5", 5, 2.0, 3.0),
    # buy near the next close, sell at an opening auction
    *[_r(f"C_time{h}_O", h, entry="close", exit="open") for h in range(1, 8)],
    _r("C_atr_1.5_2.0_h5_O", 5, 1.5, 2.0, "close", "open"),
    _r("C_atr_2.0_3.0_h5_O", 5, 2.0, 3.0, "close", "open"),
    # stop only (no target) — for event signals whose exit is fixed by the calendar
    _r("C_stop2_h5_O", 5, 2.0, np.inf, "close", "open"),
    _r("C_stop3_h5_O", 5, 3.0, np.inf, "close", "open"),
])


def _ahead(g, col: str, n: int) -> np.ndarray:
    """N x (n+1) matrix: column k is `col` k rows ahead within the symbol (k=0 is today)."""
    return np.column_stack([g[col].shift(-k).to_numpy(dtype=float) for k in range(n + 1)])


def simulate(f: pd.DataFrame, rule: ExitRule, cost: float = DEFAULT_COST,
             div_tax: float = DIV_TAX) -> pd.DataFrame:
    """f: features frame sorted by (symbol, date). One output row per input row:
    entered, outcome, days (sessions from entry to exit), gross, net."""
    f = f.reset_index(drop=True)
    H, e = rule.horizon, 1
    span = H + 2
    g = f.groupby("symbol", sort=False)
    O, Hi, Lo, C = (_ahead(g, c, span) for c in ("adj_open", "adj_high", "adj_low", "adj_close"))
    T = _ahead(g, "traded", span) == 1
    LU = _ahead(g, "locked_up", span) == 1
    LD = _ahead(g, "locked_dn", span) == 1
    FAC = _ahead(g, "factor", span) if "factor" in f else np.ones_like(O)

    n = len(f)
    c0 = f["adj_close"].to_numpy(float)
    a = f["atr_pct"].to_numpy(float)
    open_entry = rule.entry == "open"
    E = O[:, e] if open_entry else C[:, e]
    ref = c0 if open_entry else E
    stop = ref * (1 - rule.stop_atr * a) if np.isfinite(rule.stop_atr) else np.full(n, -np.inf)
    tgt = ref * (1 + rule.target_atr * a) if np.isfinite(rule.target_atr) else np.full(n, np.inf)

    if open_entry:
        cap = np.where(np.isfinite(tgt), c0 + rule.max_chase * (tgt - c0), np.inf)
        ok_px = (E > stop) & (E < cap)
    else:
        ok_px = E <= c0 * (1 + rule.max_chase_atr * a)
    first = e if open_entry else e + 1
    if rule.exit == "open":
        last, exit_col = e + H - 1, ("O", e + H)
    else:
        last = e + H - 1 if open_entry else e + H
        exit_col = ("C", last)
    final_px = (O if exit_col[0] == "O" else C)[:, exit_col[1]]
    entered = T[:, e] & ~LU[:, e] & np.isfinite(E) & ok_px & np.isfinite(final_px)

    exit_px = np.full(n, np.nan)
    exit_k = np.full(n, np.nan)
    outcome = np.full(n, "", dtype=object)
    alive = entered.copy()

    def close_out(mask, px, k, label):
        nonlocal alive
        m = mask & alive
        exit_px[m] = px[m] if np.ndim(px) else px
        exit_k[m] = k
        outcome[m] = label
        alive = alive & ~m

    for k in range(first, last + 1):
        o, h, l, t = O[:, k], Hi[:, k], Lo[:, k], T[:, k]
        if not (open_entry and k == e):                       # entry day's open is the entry
            close_out(t & (o <= stop), o, k, "gap_stop")
            close_out(t & (o >= tgt), o, k, "gap_target")
        hit_s, hit_t = t & (l <= stop), t & (h >= tgt)
        nxt = O[:, k + 1]
        close_out(hit_s & LD[:, k], np.where(np.isfinite(nxt), nxt, C[:, k]), k + 1, "locked_stop")
        close_out(hit_s, stop, k, "stop")                     # stop first when both touched
        close_out(hit_t, tgt, k, "target")
    close_out(np.ones(n, bool), final_px, exit_col[1], "time")

    # dividends collected: ex-dates after the entry day, up to and including the exit day
    # (an exit at the ex-date's open still collects it). Bonus/rights (big factors) aren't taxed.
    cash = np.where((FAC < 1) & (FAC >= 0.85), 1 - FAC, 0.0)
    ks = np.arange(span + 1)[None, :]
    held = (ks > e) & (ks <= np.nan_to_num(exit_k, nan=-1)[:, None])
    tax = div_tax * (cash * held).sum(axis=1)

    gross = exit_px / E - 1
    # open entry: sessions held incl. the entry day; close entry: nights held
    days = exit_k - e + (1 if open_entry else 0)
    out = pd.DataFrame({"entered": entered, "outcome": np.where(entered, outcome, "skip"),
                        "days": np.where(entered, days, np.nan),
                        "gross": np.where(entered, gross - tax, np.nan)})
    out["net"] = out["gross"] - cost
    return out


def outcome_panel(f: pd.DataFrame, rules: dict[str, ExitRule] | None = None,
                  cost: float = DEFAULT_COST) -> pd.DataFrame:
    """Simulate every rule for every row; wide frame aligned with f (sorted by symbol, date)."""
    rules = rules or RULES
    f = f.sort_values(["symbol", "date"]).reset_index(drop=True)
    parts = [f[["symbol", "date"]]]
    for name, r in rules.items():
        parts.append(simulate(f, r, cost).add_prefix(f"{name}__"))
    return pd.concat(parts, axis=1)
