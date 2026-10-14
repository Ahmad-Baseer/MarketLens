"""Dividend run-up signals — the one family that passed every research test
(reports/research_step2.md section 3).

Two published variants, both: cash dividend (no bonus/rights attached), yield 2-7%
at the signal day's close, a top-200 liquid stock, bought near the close (PSX's
close is the VWAP of the last 30 minutes) and sold at the ex-date's opening
auction, so the dividend is collected.

  DIV_K5   "Dividend run-up": entry 5 sessions before the ex-date.
           Published the evening before the entry day.
  DIV_3W   "Early dividend entry": entry the session after the announcement,
           held to the ex-date (about 3 weeks). Published the evening of the
           announcement. Needs at least 2 nights to the ex-date.

Entry is skipped if the stock doesn't trade, is locked at the upper circuit, or
has already run more than 1 ATR above the signal close (never chase). A
protective stop sits 3 ATR below the entry price.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mbf.signals.calendar import Calendar

YIELD_MIN, YIELD_MAX = 0.02, 0.07
STOP_ATR = 3.0
CHASE_ATR = 1.0
K = 5
ENGINE_VERSION = "div-1.0"
TYPES = {
    "DIV_K5": "Dividend run-up",
    "DIV_3W": "Early dividend entry",
}
# Replayed day by day, DIV_3W (2-7% yield) made +0.27% net with the stop and its edge over
# controls was t 1.8 in 2018-2022, short of the bar. It is still computed in the backtest for
# transparency, but only these types are published.
PUBLISHED_TYPES = ("DIV_K5",)


def _known_by(announced_at: pd.Series, session: pd.Timestamp) -> pd.Series:
    """Announced by the evening publication (18:00 PKT) of `session`."""
    return announced_at <= session + pd.Timedelta(hours=18)


def annotate(e: pd.DataFrame, cal: Calendar) -> pd.DataFrame:
    """Add each event's K5 entry session and the session its announcement was
    first actionable on (evening publication at 18:00 PKT)."""
    e = e.copy()
    e["k5_entry"] = [cal.shift(x, -K) for x in e["ex_date"]]
    e["ann_session"] = [cal.all[cal.all.searchsorted(a - pd.Timedelta(hours=18))]
                        for a in e["announced_at"]]
    return e


def candidates(events: pd.DataFrame, asof: pd.Timestamp, cal: Calendar) -> pd.DataFrame:
    """Upcoming cash-dividend ex-dates known at `asof` (any yield), with their dates."""
    e = events[_known_by(events["announced_at"], asof) & (events["ex_date"] > asof)]
    if e.empty:
        return e
    e = e.sort_values("announced_at").drop_duplicates(["symbol", "ex_date"], keep="last")
    return annotate(e, cal)


def generate(events: pd.DataFrame, feats: pd.DataFrame, asof: pd.Timestamp,
             cal: Calendar) -> list[dict]:
    """Signals to publish on the evening of session `asof`.
    feats: one row per symbol for `asof` (close, atr_pct, in_universe, ...)."""
    e = candidates(events, asof, cal)
    if e.empty:
        return []
    nxt = cal.shift(asof, 1)
    f = feats.set_index("symbol")
    out = []
    for r in e.itertuples():
        if r.has_bonus or r.has_right or r.symbol not in f.index:
            continue
        kinds = []
        if r.k5_entry == nxt:
            kinds.append("DIV_K5")
        if r.ann_session == asof and cal.between(nxt, r.ex_date) >= 2 and r.k5_entry > nxt:
            kinds.append("DIV_3W")
        if not kinds:
            continue
        x = f.loc[r.symbol]
        if not bool(x["in_universe"]) or not np.isfinite(x["close"]) or x["close"] <= 0:
            continue
        yld = r.div_rs / x["close"]
        if not (YIELD_MIN <= yld < YIELD_MAX):
            continue
        atr = float(x["atr_pct"])
        for kind in kinds:
            out.append({
                "id": f"{kind}-{r.symbol}-{pd.Timestamp(r.ex_date):%Y%m%d}",
                "type": kind, "engine": ENGINE_VERSION,
                "symbol": r.symbol, "signal_date": asof, "entry_date": nxt,
                "exit_date": pd.Timestamp(r.ex_date), "ex_date": pd.Timestamp(r.ex_date),
                "nights": cal.between(nxt, r.ex_date),
                "close_at_signal": float(x["close"]), "atr_pct": atr,
                "max_entry_price": float(x["close"]) * (1 + CHASE_ATR * atr),
                "stop_atr": STOP_ATR, "stop_pct": STOP_ATR * atr,
                "div_rs": float(r.div_rs), "div_pct": float(r.div_pct), "par": float(r.par),
                "yield": float(yld), "announced_at": r.announced_at,
                "bc_from": r.bc_from, "bc_to": r.bc_to, "ex_basis": r.ex_basis,
                "event_source": r.source, "details": r.details,
                "to_rank": float(x.get("to_rank", np.nan)),
                "turnover_med20": float(x.get("med_to20", np.nan)),
            })
    return out
