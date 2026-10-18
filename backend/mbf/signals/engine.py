"""Evening signal run: after the day's data is in, decide what to publish for the
next session, track every signal published so far, and write the JSON the web app
reads.

The backtest is the same engine replayed over history: for each past session it
sees only payouts announced by that evening and prices up to that close.
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from mbf import store
from mbf.research import features as featmod
from mbf.signals import dividend, ledger, payouts
from mbf.signals.calendar import Calendar

log = logging.getLogger(__name__)

BACKTEST_FROM = pd.Timestamp("2018-01-01")     # payout history (AKD) starts in 2018
# A signal is only worth publishing while you can still act on it: the buy happens in the
# last 30 minutes of the entry day (from 15:00 Mon-Thu), so a run that catches up later
# than this (laptop asleep, job delayed) publishes nothing for that day.
PUBLISH_CUTOFF = pd.Timedelta(hours=15)
FEATURE_COLS = ["symbol", "date", "close", "atr_pct", "in_universe", "to_rank", "med_to20",
                "dma50", "dma200", "r1", "r5", "r20", "vol_ratio", "close_loc", "rsi14", "off_hi250",
                "breadth50", "mkt_dma200"]


def _daily() -> pd.DataFrame:
    return store.read_parquet(store.path("prices", "daily.parquet"))


def _sessions(daily: pd.DataFrame) -> pd.DatetimeIndex:
    t = daily[daily["traded"].astype(bool)]
    return pd.DatetimeIndex(np.sort(t["date"].unique()))


def features(daily: pd.DataFrame, since: pd.Timestamp | None = None) -> pd.DataFrame:
    """Signal-time features. Recomputed from prices (needs ~1 year of history per day)."""
    d = daily
    if since is not None:
        d = daily[daily["date"] >= since - pd.Timedelta(days=500)]
    f = featmod.compute(d)
    if since is not None:
        f = f[f["date"] >= since]
    return f[FEATURE_COLS]


def run_backtest(daily: pd.DataFrame | None = None, feats: pd.DataFrame | None = None) -> pd.DataFrame:
    daily = daily if daily is not None else _daily()
    s = _sessions(daily)
    cal = Calendar(s)
    ev = payouts.all_events(cal.all)
    feats = feats if feats is not None else features(daily)
    by_day = {d: g for d, g in feats.groupby("date")}
    # sessions on which something could trigger: the evening before a K5 entry, or
    # the announcement session (DIV_3W)
    c = dividend.annotate(ev, cal)
    trig = set()
    for r in c.itertuples():
        trig.add(cal.shift(r.k5_entry, -1))
        trig.add(r.ann_session)
    trig = sorted(d for d in trig if BACKTEST_FROM <= d <= s[-1] and d in by_day)
    sigs = []
    for d in trig:
        if d == s[-1]:
            continue                       # tonight's signals are the live run's job
        sigs += dividend.generate(ev, by_day[d], d, cal)
    bt = ledger.write_backtest(sigs)
    log.info("backtest: %d signals from %d trigger sessions (%s..%s)", len(bt), len(trig),
             trig[0].date() if trig else None, trig[-1].date() if trig else None)
    return bt


def publishable(sigs: list[dict], now: pd.Timestamp) -> tuple[list[dict], list[dict]]:
    """(still actionable, too late): a signal can be acted on until 15:00 PKT of its entry day."""
    ok = [x for x in sigs if now < x["entry_date"] + PUBLISH_CUTOFF]
    return ok, [x for x in sigs if not now < x["entry_date"] + PUBLISH_CUTOFF]


def run_live(daily: pd.DataFrame | None = None, now: pd.Timestamp | None = None,
             publish: bool = True, feats: pd.DataFrame | None = None) -> list[dict]:
    daily = daily if daily is not None else _daily()
    s = _sessions(daily)
    cal = Calendar(s)
    asof = s[-1]
    ev = payouts.all_events(cal.all)
    feats = feats if feats is not None else features(daily, since=asof)
    today = feats[feats["date"] == asof]
    sigs = [x for x in dividend.generate(ev, today, asof, cal) if x["type"] in dividend.PUBLISHED_TYPES]
    now = now or pd.Timestamp.now(tz="Asia/Karachi").tz_localize(None)
    sigs, late = publishable(sigs, now)
    if late:
        log.warning("not publishing %d signal(s) for %s: their buy window has passed (%s)", len(late),
                    asof.date(), ", ".join(x["symbol"] for x in late))
    if publish:
        ledger.publish(sigs, asof, now)
    return sigs


def track_all(daily: pd.DataFrame | None = None) -> pd.DataFrame:
    daily = daily if daily is not None else _daily()
    sig = ledger.load("all")
    out = ledger.track(sig, daily)
    if not out.empty:
        store.write_parquet(out, store.path(*ledger.OUTCOMES))
    return out


def summary(sig: pd.DataFrame, out: pd.DataFrame) -> pd.DataFrame:
    m = sig.merge(out, on="id")
    m = m[m["status"] == "closed"]
    m["yield_band"] = pd.cut(m["yield"], [0.02, 0.03, 0.045, 0.07], right=False,
                             labels=["2-3%", "3-4.5%", "4.5-7%"])
    g = m.groupby(["type", "yield_band"], observed=True)["net"]
    return pd.DataFrame({"n": g.size(), "win": g.apply(lambda x: (x > 0).mean()),
                         "mean_net": g.mean(), "median_net": g.median()})


def run_evening(daily: pd.DataFrame | None = None, dry_run: bool = False) -> dict:
    """Everything after the day's data is in: publish, replay, track, warn, write JSON.
    dry_run: compute tonight's signals but don't append them to the live ledger
    (they appear in the web JSON marked 'preview')."""
    from mbf.signals import par
    from mbf.signals import warnings as warnmod
    from mbf.signals import web

    daily = daily if daily is not None else _daily()
    s = _sessions(daily)
    if not store.path("ref", "par_values.parquet").exists():
        par.build(s)
    cal = Calendar(s)
    asof = s[-1]
    feats = features(daily)                              # once: live, backtest and web pages
    live = run_live(daily, publish=not dry_run, feats=feats[feats["date"] == asof])
    bt = run_backtest(daily, feats)
    out = track_all(daily)
    feats_today = feats[feats["date"] == asof]
    try:
        warn = warnmod.compute(feats_today, asof, s)
    except Exception as e:                               # warnings are context, never block
        log.warning("warnings failed: %s", e)
        warn = pd.DataFrame(columns=["symbol", "warning", "since", "title", "detail"])
    store.write_parquet(warn, store.path("ledger", "warnings.parquet"))
    today = web.write_all(daily, feats, cal, payouts.all_events(cal.all), warn,
                          preview=live if dry_run else None)
    return {"asof": str(asof.date()), "tonight_signals": len(live),
            "published_to_ledger": 0 if dry_run else len(live), "backtest_signals": len(bt),
            "tracked": len(out), "warnings": len(warn), "tonight": len(today.get("tonight", [])),
            "upcoming": len(today.get("upcoming", []))}
