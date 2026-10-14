"""Published signals and what happened to them.

LIVE signals are append-only: each evening's publication is written once to
data/ledger/published/<date>.json and appended to signals.parquet; an existing id
is never rewritten. BACKTEST signals (the engine replayed over history with only
the information available each day) live in backtest.parquet and can be rebuilt.
Outcomes are recomputed from prices on every run, using the same execution rules
as the research simulator (research/outcomes.py):
  * entry near the close of the entry day; skipped if the stock didn't trade, was
    locked at the upper circuit, or closed more than 1 ATR above the signal close;
  * protective stop checked from the next session: a gap below it exits at the open,
    a touch exits at the stop (a lower-circuit-locked day exits at the next open);
  * otherwise out at the ex-date's opening auction, dividend collected (15% tax).
Returns use dividend-adjusted prices, so they include the dividend.
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from mbf import store
from mbf.research.features import LOCK_MOVE
from mbf.research.outcomes import DEFAULT_COST, DIV_TAX

log = logging.getLogger(__name__)

LIVE = ("ledger", "signals.parquet")
BACKTEST = ("ledger", "backtest.parquet")
OUTCOMES = ("ledger", "outcomes.parquet")


def _json_default(o):
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if o is pd.NaT or (isinstance(o, float) and np.isnan(o)):
        return None
    return str(o)


def publish(signals: list[dict], session: pd.Timestamp, published_at: pd.Timestamp) -> int:
    """Append tonight's live signals. Returns how many were new."""
    if not signals:
        return 0
    p = store.path(*LIVE)
    old = store.read_parquet(p)
    have = set(old["id"]) if not old.empty else set()
    new = [dict(s, published_at=published_at, mode="live") for s in signals if s["id"] not in have]
    if not new:
        return 0
    day = store.path("ledger", "published", f"{session:%Y-%m-%d}.json")
    if not day.exists():                       # the evening's record is written exactly once
        day.parent.mkdir(parents=True, exist_ok=True)
        day.write_text(json.dumps(new, default=_json_default, indent=1), encoding="utf-8")
    df = pd.DataFrame(new)
    allr = pd.concat([old, df], ignore_index=True) if not old.empty else df
    store.write_parquet(allr, p)
    log.info("ledger: published %d new live signals for %s", len(new), session.date())
    return len(new)


def write_backtest(signals: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(signals)
    if not df.empty:
        df["mode"] = "backtest"
        df["published_at"] = df["signal_date"] + pd.Timedelta(hours=18, minutes=30)
    store.write_parquet(df, store.path(*BACKTEST))
    return df


def load(which: str = "all") -> pd.DataFrame:
    parts = []
    if which in ("all", "live"):
        parts.append(store.read_parquet(store.path(*LIVE)))
    if which in ("all", "backtest"):
        parts.append(store.read_parquet(store.path(*BACKTEST)))
    parts = [p for p in parts if not p.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _px(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily[["symbol", "date", "open", "high", "low", "close", "ldcp", "traded",
               "adj_open", "adj_high", "adj_low", "adj_close", "factor"]].copy()
    move = d["close"] / d["ldcp"].where(d["ldcp"] > 0) - 1
    flat = d["high"] == d["low"]
    d["locked_up"] = d["traded"].astype(bool) & flat & (move >= LOCK_MOVE)
    d["locked_dn"] = d["traded"].astype(bool) & flat & (move <= -LOCK_MOVE)
    return d.set_index(["symbol", "date"]).sort_index()


def track(signals: pd.DataFrame, daily: pd.DataFrame, cost: float = DEFAULT_COST,
          div_tax: float = DIV_TAX) -> pd.DataFrame:
    """Outcome of every signal given prices up to the last session in `daily`."""
    if signals.empty:
        return pd.DataFrame()
    px = _px(daily[daily["symbol"].isin(signals["symbol"].unique())])
    last = daily["date"].max()
    rows = []
    for s in signals.itertuples():
        o = {"id": s.id, "status": "", "entry_price": np.nan, "exit_price": np.nan,
             "exit_date": pd.NaT, "stop_price": np.nan, "net": np.nan, "gross": np.nan,
             "dividend": np.nan, "nights_held": np.nan, "last_price": np.nan, "as_of": last}
        try:
            h = px.loc[s.symbol]
        except KeyError:
            rows.append(dict(o, status="no_data"))
            continue
        h = h[h.index >= s.entry_date]
        if s.entry_date > last or h.empty:
            rows.append(dict(o, status="pending_entry"))
            continue
        e = h.iloc[0]
        if h.index[0] != s.entry_date or not bool(e["traded"]):
            rows.append(dict(o, status="skipped", reason="did not trade on the entry day"))
            continue
        if bool(e["locked_up"]):
            rows.append(dict(o, status="skipped", reason="locked at the upper circuit"))
            continue
        if e["close"] > s.max_entry_price:
            rows.append(dict(o, status="skipped",
                             reason=f"closed at {e['close']:.2f}, above the maximum entry {s.max_entry_price:.2f}"))
            continue
        a_in = e["adj_close"]
        stop_adj = a_in * (1 - s.stop_pct)
        o.update(entry_price=float(e["close"]), stop_price=float(e["close"] * (1 - s.stop_pct)))
        after = h.iloc[1:]
        exit_adj = exit_raw = None
        exit_date, label = None, None
        for i, (d, r) in enumerate(after.iterrows()):
            if d >= s.exit_date:
                if d == s.exit_date and bool(r["traded"]) and np.isfinite(r["open"]):
                    exit_adj, exit_raw, exit_date, label = r["adj_open"], r["open"], d, "exit_ex_date"
                elif d >= s.exit_date and bool(r["traded"]):
                    # no print at the ex-date open: first available open
                    exit_adj, exit_raw, exit_date, label = r["adj_open"], r["open"], d, "exit_late"
                if exit_adj is not None:
                    break
                continue
            if not bool(r["traded"]):
                continue
            if r["adj_open"] <= stop_adj:
                exit_adj, exit_raw, exit_date, label = r["adj_open"], r["open"], d, "stop_gap"
                break
            if r["adj_low"] <= stop_adj:
                if bool(r["locked_dn"]):
                    nxt = after.iloc[i + 1] if i + 1 < len(after) else None
                    if nxt is None:
                        break                           # locked down, next open not known yet
                    exit_adj, exit_raw, exit_date, label = nxt["adj_open"], nxt["open"], after.index[i + 1], "stop_locked"
                else:
                    ratio = stop_adj / r["adj_close"]
                    exit_adj, exit_raw, exit_date, label = stop_adj, r["close"] * ratio, d, "stop"
                break
        if exit_adj is None:
            cur = h.iloc[-1]
            gross = cur["adj_close"] / a_in - 1
            rows.append(dict(o, status="open", last_price=float(cur["close"]),
                             gross=gross, net=gross - cost,
                             nights_held=len(h) - 1))
            continue
        span = h[(h.index > s.entry_date) & (h.index <= exit_date)]["factor"].fillna(1.0)
        cash = float(np.where((span < 1) & (span >= 0.85), 1 - span, 0.0).sum())
        gross = exit_adj / a_in - 1 - div_tax * cash
        got_div = label in ("exit_ex_date", "exit_late") and exit_date >= s.ex_date
        rows.append(dict(o, status="closed", outcome=label, exit_price=float(exit_raw),
                         exit_date=exit_date, gross=gross, net=gross - cost,
                         dividend=float(s.div_rs) if got_div else 0.0,
                         nights_held=int((h.index <= exit_date).sum() - 1)))
    out = pd.DataFrame(rows)
    return out
