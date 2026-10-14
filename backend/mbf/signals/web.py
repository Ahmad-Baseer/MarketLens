"""The JSON files the web app serves (data/web/):

  today.json            home page: tonight's signals (3 strongest first), open
                        positions, upcoming dividend calendar, market context
  history.json          every published-type signal by week, backtest and live,
                        with what happened (stop = the lower limit was hit)
  signals/<id>.json     one signal's full justification
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from mbf import config, store
from mbf.signals import dividend, ledger
from mbf.signals.calendar import Calendar
from mbf.signals.ledger import _json_default

log = logging.getLogger(__name__)

DISCLAIMER = ("Research signals, not investment advice. Results describe the past; trades can "
              "lose money. Prices are PSX official closes and opening-auction prints; costs of 0.6% "
              "per round trip and 15% dividend tax are already deducted.")
OUTCOME_TEXT = {
    "exit_ex_date": "Sold at the ex-date opening auction (as planned), dividend collected",
    "exit_late": "Sold at the first open after the ex-date (no ex-date print)",
    "stop": "Protective stop (lower limit) hit",
    "stop_gap": "Opened below the protective stop (lower limit) — sold at the open",
    "stop_locked": "Stop hit on a lower-circuit day — sold at the next open",
}
BANDS = [0.02, 0.03, 0.045, 0.07]
BAND_LABELS = ["2-3%", "3-4.5%", "4.5-7%"]


def _write(rel: tuple, obj) -> None:
    p = store.path("web", *rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(_clean(obj), default=_json_default, indent=1), encoding="utf-8")
    tmp.replace(p)


def _clean(o):
    """NaN/NaT -> None so the JSON is valid for browsers."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if o is pd.NaT:
        return None
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    return o


def band(y: float) -> str | None:
    i = np.searchsorted(BANDS, y, side="right") - 1
    return BAND_LABELS[i] if 0 <= i < len(BAND_LABELS) else None


def stats(sig: pd.DataFrame, out: pd.DataFrame) -> dict:
    """Track record per published type and yield band, from closed signals."""
    m = sig.merge(out, on="id")
    m = m[(m["status"] == "closed") & m["type"].isin(dividend.PUBLISHED_TYPES)]
    res = {}
    for t, g in m.groupby("type"):
        def blk(x):
            return {"n": int(len(x)), "win_rate": float((x["net"] > 0).mean()),
                    "mean_net": float(x["net"].mean()), "median_net": float(x["net"].median()),
                    "worst": float(x["net"].min()), "best": float(x["net"].max()),
                    "stopped": float(x["outcome"].str.startswith("stop").mean())}
        g = g.assign(band=g["yield"].map(band))
        res[t] = {"all": blk(g), "by_band": {b: blk(x) for b, x in g.groupby("band")},
                  "by_year": {int(y): blk(x) for y, x in g.groupby(g["signal_date"].dt.year)},
                  "since": g["signal_date"].min()}
    return res


def _names() -> pd.DataFrame:
    s = store.read_parquet(store.path("ref", "symbols.parquet"))
    return s.set_index("symbol")[["name", "sector"]] if not s.empty else pd.DataFrame(columns=["name", "sector"])


class _Fundamentals:
    """Latest company snapshot, loaded once per run."""

    def __init__(self):
        snaps = sorted(store.path("fundamentals", "snapshots").glob("*"))
        self.as_of = pd.Timestamp(snaps[-1].name) if snaps else None
        self.f = store.read_parquet(snaps[-1] / "financials.parquet") if snaps else pd.DataFrame()
        self.r = store.read_parquet(snaps[-1] / "ratios.parquet") if snaps else pd.DataFrame()
        self.f_by = dict(tuple(self.f.groupby("symbol"))) if not self.f.empty else {}
        self.r_by = dict(tuple(self.r.groupby("symbol"))) if not self.r.empty else {}

    def get(self, symbol: str, signal_date: pd.Timestamp) -> dict | None:
        """Only for recent signals: an old signal's page must not show figures that
        were published after it."""
        if self.as_of is None or signal_date < self.as_of - pd.Timedelta(days=60):
            return None
        f = self.f_by.get(symbol, pd.DataFrame(columns=["kind", "item", "period", "value"]))
        r = self.r_by.get(symbol, pd.DataFrame(columns=["kind", "item", "period", "value"]))
        out = {"as_of": self.as_of}
        a = f[(f["kind"] == "annual") & (f["item"] == "EPS")].sort_values("period")
        if len(a):
            out["eps_annual"] = [{"period": p, "eps": float(v)} for p, v in zip(a["period"], a["value"])]
        q = f[(f["kind"] == "quarterly") & (f["item"] == "EPS")]
        if len(q):
            q = q.assign(k=q["period"].str.extract(r"(\d{4})")[0] + q["period"].str[:2]).sort_values("k")
            out["eps_quarterly"] = [{"period": p, "eps": float(v)} for p, v in zip(q["period"], q["value"])]
        for item, key in [("Net Profit Margin (%)", "net_margin_pct"), ("EPS Growth (%)", "eps_growth_pct")]:
            x = r[(r["kind"] == "annual") & (r["item"] == item)].sort_values("period")
            if len(x):
                out[key] = {"period": x["period"].iloc[-1], "value": float(x["value"].iloc[-1])}
        return out


def card(s: pd.Series, o: pd.Series | None, names: pd.DataFrame, st: dict, warn: pd.DataFrame) -> dict:
    b = band(s["yield"])
    exp = st.get(s["type"], {}).get("by_band", {}).get(b, {})
    c = {
        "id": s["id"], "type": s["type"], "type_name": dividend.TYPES[s["type"]],
        "mode": s.get("mode"), "symbol": s["symbol"],
        "name": names["name"].get(s["symbol"]), "sector": names["sector"].get(s["symbol"]),
        "signal_date": s["signal_date"], "entry_date": s["entry_date"], "exit_date": s["exit_date"],
        "nights": s["nights"], "close_at_signal": s["close_at_signal"],
        "max_entry_price": s["max_entry_price"],
        "stop_price_approx": s["close_at_signal"] * (1 - s["stop_pct"]),
        "stop_pct": s["stop_pct"], "dividend_rs": s["div_rs"], "dividend_pct_of_par": s["div_pct"],
        "par": s["par"], "yield": s["yield"], "yield_band": b,
        "expected": {"win_rate": exp.get("win_rate"), "mean_net": exp.get("mean_net"),
                     "median_net": exp.get("median_net"), "n": exp.get("n")},
        "how": (f"Buy in the last 30 minutes of {s['entry_date']:%a %d %b} (PSX's close is the "
                f"average price of the last half hour), only at or below Rs {s['max_entry_price']:,.2f}. "
                f"Sell at the opening auction on {s['exit_date']:%a %d %b}, the ex-date: the dividend "
                f"of Rs {s['div_rs']:,.2f} is yours. Protective stop {s['stop_pct']:.1%} below your entry."),
        "warnings": warn[warn["symbol"] == s["symbol"]][["warning", "title"]].to_dict("records")
        if not warn.empty else [],
    }
    if o is not None:
        c["result"] = {"status": o.get("status"), "outcome": o.get("outcome"),
                       "outcome_text": OUTCOME_TEXT.get(o.get("outcome"), o.get("reason")),
                       "entry_price": o.get("entry_price"), "exit_price": o.get("exit_price"),
                       "exit_date": o.get("exit_date"), "net": o.get("net"),
                       "dividend": o.get("dividend"), "last_price": o.get("last_price")}
    return c


def detail(c: dict, s: pd.Series, x: pd.Series, px: pd.DataFrame, past: pd.DataFrame,
           st: dict, warn: pd.DataFrame, fund: dict | None) -> dict:
    """x: the stock's features at the signal date; px: its raw daily prices around the trade."""
    sym = s["symbol"]
    eps = ((fund or {}).get("eps_annual") or [{}])[-1].get("eps")
    tr = st.get(s["type"], {}).get("all", {})
    rank = x.get("to_rank", np.nan)
    if s.get("ex_basis") == "book_closure" and pd.notna(s.get("bc_from")):
        lag = ("one session before it, under T+1 settlement" if s["bc_from"] >= pd.Timestamp(config.T1_SETTLEMENT_FROM)
               else "two sessions before it, under T+2 settlement")
        ex_line = (f"Book closure starts {s['bc_from']:%a %d %b}, so the ex-date is {s['ex_date']:%a %d %b %Y}: "
                   f"{lag}.")
    else:
        ex_line = f"The ex-date is {s['ex_date']:%a %d %b %Y}."
    why = [
        f"{c['name'] or sym} announced a cash dividend of Rs {s['div_rs']:,.2f} per share "
        f"({s['div_pct']:.4g}% of the Rs {s['par']:.4g} par value) on {s['announced_at']:%d %b %Y}.",
        ex_line,
        f"At the signal-day close (Rs {s['close_at_signal']:,.2f}) the dividend is a {s['yield']:.1%} yield, inside "
        "the 2-7% band where the run-up has been reliable. Above 7% the market tends to price the payout early.",
        f"Since 2018, {tr.get('n', 0)} signals like this (bought 5 sessions before the ex-date, sold at the "
        f"ex-date opening auction) made {tr.get('mean_net', float('nan')):+.2%} on average after costs and tax "
        f"and won {tr.get('win_rate', float('nan')):.0%} of the time. They beat comparable stocks over the same "
        "days in 8 of 9 years.",
        (f"It ranked #{int(rank)} by recent turnover among PSX stocks, so the closing price and the opening "
         "auction are realistic fills." if pd.notna(rank) else
         "It is among the 200 most-traded PSX stocks, so the closing price and the opening auction are realistic fills."),
    ]
    if eps is not None and eps > 0:
        why.append(f"The dividend is {s['div_rs'] / eps:.0%} of last full-year EPS (Rs {eps:,.2f})"
                   + (", covered by earnings." if s["div_rs"] <= eps else
                      ", more than a year's earnings. Coverage doesn't change the run-up, but it matters longer term."))
    tech = {k: (float(x[k]) if k in x and pd.notna(x[k]) else None)
            for k in ("dma50", "dma200", "r5", "r20", "rsi14", "off_hi250", "atr_pct", "to_rank", "med_to20")}
    return dict(c, why=why,
                event={"announced_at": s["announced_at"], "details": s.get("details"),
                       "book_closure": [s.get("bc_from"), s.get("bc_to")], "ex_date": s["ex_date"],
                       "ex_basis": s.get("ex_basis"), "source": s.get("event_source")},
                fundamentals=fund, technicals=tech, technicals_date=s["signal_date"],
                warnings_detail=warn[warn["symbol"] == sym].to_dict("records") if not warn.empty else [],
                track_record=st.get(s["type"]),
                this_stock_before=past.to_dict("records"),
                prices=[{"date": d, "open": o, "high": hi, "low": lo, "close": cl, "volume": v}
                        for d, o, hi, lo, cl, v in zip(px["date"], px["open"], px["high"], px["low"],
                                                      px["close"], px["volume"])])


def _curve(cards: list[dict], stake: float = 100_000) -> list[dict]:
    """Cumulative profit of putting `stake` on every closed signal, by exit week."""
    done = [c for c in cards if (c.get("result") or {}).get("status") == "closed"]
    if not done:
        return []
    d = pd.DataFrame({"date": pd.to_datetime([c["result"]["exit_date"] for c in done]),
                      "pnl": [c["result"]["net"] * stake for c in done]})
    d["week"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    w = d.groupby("week").agg(pnl=("pnl", "sum"), n=("pnl", "size")).sort_index()
    w["cum"] = w["pnl"].cumsum()
    w["trades"] = w["n"].cumsum()
    return [{"week": k, "cum_profit": float(r.cum), "trades": int(r.trades)} for k, r in w.iterrows()]


def _week_block(wk: pd.Timestamp, cs: list[dict]) -> dict:
    done = [c for c in cs if c.get("result") and c["result"]["status"] == "closed"]
    return {"week": wk, "signals": cs, "n": len(cs), "closed": len(done),
            "wins": sum(1 for c in done if (c["result"]["net"] or 0) > 0),
            "stops": sum(1 for c in done if (c["result"]["outcome"] or "").startswith("stop")),
            "skipped": sum(1 for c in cs if (c.get("result") or {}).get("status") == "skipped"),
            "mean_net": float(np.mean([c["result"]["net"] for c in done])) if done else None}


WARNING_ORDER = {"leaving_kse30": 0, "after_results_beat": 1, "after_ex_date": 2,
                 "unusual_movement_letter": 3, "weak_close": 4, "volume_spike": 5}


def write_all(daily: pd.DataFrame, feats: pd.DataFrame, cal: Calendar,
              events: pd.DataFrame, warn: pd.DataFrame, preview: list[dict] | None = None) -> dict:
    """feats: features for every symbol-day (the evening run computes them once)."""
    sig = ledger.load("all")
    if preview:
        sig = pd.concat([sig, pd.DataFrame(preview).assign(mode="preview")], ignore_index=True)
    out = store.read_parquet(store.path(*ledger.OUTCOMES))
    if sig.empty:
        return {}
    names = _names()
    sig = sig[sig["type"].isin(dividend.PUBLISHED_TYPES)]
    # a live signal supersedes its backtest twin
    sig = sig.sort_values("mode", key=lambda m: m.map({"live": 0, "preview": 1, "backtest": 2})).drop_duplicates("id")
    st = stats(sig, out)
    o_by = out.set_index("id") if not out.empty else pd.DataFrame()
    asof = cal.last
    nxt = cal.shift(asof, 1)
    feats_today = feats[feats["date"] == asof]

    def oc(i):
        return o_by.loc[i].to_dict() if i in o_by.index else None

    # (to_dict, not itertuples: "yield" is a Python keyword and would be renamed)
    cards = {r["id"]: card(pd.Series(r), oc(r["id"]), names, st, warn) for r in sig.to_dict("records")}

    # tonight: signals published this evening, strongest first by the track record of their yield band
    tonight = [cards[i] for i in sig[(sig["signal_date"] == asof)]["id"]]
    tonight.sort(key=lambda c: (c["expected"]["mean_net"] or 0, c["yield"]), reverse=True)
    for k, c in enumerate(tonight):
        c["rank"] = k + 1
        c["strongest"] = k < 3
    active = sorted([c for c in cards.values() if c.get("result")
                     and c["result"]["status"] in ("open", "pending_entry") and c["signal_date"] < asof],
                    key=lambda c: c["exit_date"])

    # upcoming: announced cash dividends whose run-up window opens within ~15 sessions
    up = dividend.candidates(events, asof, cal)
    upcoming = []
    if not up.empty:
        f = feats_today.set_index("symbol")
        for r in up.sort_values("k5_entry").itertuples():
            if r.has_bonus or r.has_right or r.k5_entry <= nxt or cal.between(asof, r.k5_entry) > 15:
                continue
            px = f["close"].get(r.symbol, np.nan)
            y = r.div_rs / px if px and np.isfinite(px) else np.nan
            liquid = bool(f["in_universe"].get(r.symbol, False))
            upcoming.append({"symbol": r.symbol, "name": names["name"].get(r.symbol),
                             "dividend_rs": r.div_rs, "ex_date": r.ex_date, "last_close": px,
                             "signal_evening": cal.shift(r.k5_entry, -1), "entry_date": r.k5_entry,
                             "yield_now": y, "liquid": liquid,
                             "qualifies_now": bool(liquid and np.isfinite(y)
                                                   and dividend.YIELD_MIN <= y < dividend.YIELD_MAX)})

    idx = store.read_parquet(store.path("indices", "eod.parquet"))
    k = idx[idx["symbol"] == "KSE100"].sort_values("date")
    market = {}
    if len(k) > 21:
        c0 = k["close"].iloc[-1]
        market = {"kse100": float(c0), "date": k["date"].iloc[-1],
                  "chg_1d": float(c0 / k["close"].iloc[-2] - 1), "chg_5d": float(c0 / k["close"].iloc[-6] - 1),
                  "chg_20d": float(c0 / k["close"].iloc[-21] - 1),
                  "above_200d": bool(c0 > k["close"].tail(200).mean()) if len(k) >= 200 else None,
                  "spark": [{"date": d, "close": float(v)} for d, v in zip(k["date"].tail(60), k["close"].tail(60))]}
        b = feats_today["breadth50"].dropna() if "breadth50" in feats_today else pd.Series(dtype=float)
        market["breadth50"] = float(b.iloc[0]) if len(b) else None

    # warnings on liquid stocks (the ones someone might be about to buy)
    wl = []
    if not warn.empty:
        liq = set(feats_today.loc[feats_today["in_universe"].astype(bool), "symbol"])
        ww = warn[warn["symbol"].isin(liq)].copy()
        ww["name"] = ww["symbol"].map(names["name"])
        ww["order"] = ww["warning"].map(WARNING_ORDER).fillna(9)
        ww = ww.sort_values(["order", "symbol"])
        wl = ww[["symbol", "name", "warning", "title", "detail", "since"]].to_dict("records")

    gen = pd.Timestamp.now(tz="Asia/Karachi").tz_localize(None)
    today = {"generated_at": gen, "asof": asof, "next_session": nxt, "tonight": tonight, "active": active,
             "upcoming": upcoming, "market": market, "warnings": wl,
             "track_record": {t: {"all": v["all"], "by_band": v["by_band"], "since": v["since"]}
                              for t, v in st.items()},
             "disclaimer": DISCLAIMER}
    _write(("today.json",), today)

    # history: an index plus one file per year (weeks run Monday-Friday, by entry date)
    weeks: dict[pd.Timestamp, list] = {}
    for c in sorted(cards.values(), key=lambda c: (c["entry_date"], c["symbol"])):
        wk = (c["entry_date"] - pd.Timedelta(days=c["entry_date"].weekday())).normalize()
        weeks.setdefault(wk, []).append(c)
    years = sorted({wk.year for wk in weeks}, reverse=True)
    for y in years:
        blocks = [_week_block(wk, cs) for wk, cs in sorted(weeks.items(), reverse=True) if wk.year == y]
        _write(("history", f"{y}.json"), {"year": y, "weeks": blocks})
    _write(("history.json",), {"generated_at": gen, "years": years, "track_record": st,
                               "curve": _curve(list(cards.values())), "disclaimer": DISCLAIMER})

    # a detail page for every signal, as of its own signal date
    fund = _Fundamentals()
    fx = feats.set_index(["symbol", "date"]).sort_index()
    sub = daily[daily["symbol"].isin(sig["symbol"].unique())].sort_values("date")
    px_by = {sym: g.reset_index(drop=True) for sym, g in sub.groupby("symbol")}
    sig_by = sig.set_index("id")
    for i in cards:
        srow = sig_by.loc[i].copy()
        srow["id"] = i
        sym = srow["symbol"]
        key = (sym, srow["signal_date"])
        x = fx.loc[key] if key in fx.index else pd.Series(dtype=float)
        h = px_by.get(sym, daily.iloc[0:0])
        lo = int(h["date"].searchsorted(srow["entry_date"])) - 60
        hi = int(h["date"].searchsorted(srow["exit_date"])) + 6
        h = h.iloc[max(lo, 0):hi]
        prev = [cards[j] for j in sig[(sig["symbol"] == sym) & (sig["signal_date"] < srow["signal_date"])]
                .sort_values("signal_date")["id"]]
        past = pd.DataFrame([{"id": p["id"], "signal_date": p["signal_date"], "ex_date": p["exit_date"],
                              "yield": p["yield"], "net": (p.get("result") or {}).get("net"),
                              "outcome": (p.get("result") or {}).get("outcome")} for p in prev[-8:]])
        _write(("signals", f"{i}.json"),
               detail(cards[i], srow, x, h, past, st, warn, fund.get(sym, srow["signal_date"])))
    log.info("web: %d tonight, %d active, %d upcoming, %d warnings, %d signal pages, %d years of history",
             len(tonight), len(active), len(upcoming), len(wl), len(cards), len(years))
    return today
