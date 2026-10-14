"""Risk warnings: situations where buying has reliably done WORSE than a random
comparable stock (research_step2.md section 4, research_new_data.md section 2).
They are shown on stock and signal pages; they never generate trades.
"""
from __future__ import annotations

import io
import logging
import re

import numpy as np
import pandas as pd

from mbf import store

log = logging.getLogger(__name__)

WARNINGS = {
    "after_ex_date": ("Just went ex-dividend",
                      "Buying in the 3-5 sessions after an ex-date did 0.6-0.7% worse than comparable "
                      "stocks, in at least 8 of 9 years."),
    "weak_close": ("Closed at the day's low on a big drop",
                   "Buying at such a close (bottom 15% of the day's range, down 3%+) and selling at "
                   "the next open did 0.4% worse than comparable stocks; these stocks keep falling overnight."),
    "volume_spike": ("Unusual volume (over 3x normal)",
                     "Stocks trading over 3x their usual value have done 0.2% worse than comparable "
                     "stocks over the following week."),
    "unusual_movement_letter": ("PSX unusual-movement notice",
                                "PSX queried the company about unusual price/volume moves in the last "
                                "20 sessions. Such stocks have lagged comparable stocks."),
    "after_results_beat": ("Just reported a big earnings jump",
                           "In the days after quarterly EPS beat the same quarter last year by a wide "
                           "margin, buyers did 0.4-0.7% worse than comparable stocks over the next week "
                           "(the good news was already in the price)."),
    "leaving_kse30": ("Leaving the KSE-30 index",
                      "Stocks removed from KSE-30 did 1.3% worse than comparable stocks in the week "
                      "after the notice, in 10 of 11 years."),
}


# 80th percentile of (quarterly EPS - same quarter last year) / price, 2018-2026 results
BEAT_SURPRISE = 0.053


def _results_beats(since: pd.Timestamp, close: pd.Series) -> dict[str, pd.Timestamp]:
    """Quarterly EPS first seen (by the evening company sweep) since `since` that beat the
    same quarter last year by >= BEAT_SURPRISE of the price."""
    h = store.read_parquet(store.path("fundamentals", "financials_history.parquet"))
    if h.empty:
        return {}
    first_sweep = h["first_seen"].min()
    q = h[(h["kind"] == "quarterly") & (h["item"] == "EPS")].copy()
    q[["qtr", "yr"]] = q["period"].str.extract(r"(Q\d)\s+(\d{4})")
    q = q.dropna(subset=["qtr", "yr"])
    q["yr"] = q["yr"].astype(int)
    new = q[(q["first_seen"] >= since) & (q["first_seen"] > first_sweep)]
    prev = q.assign(yr=q["yr"] + 1)[["symbol", "qtr", "yr", "value"]].rename(columns={"value": "prev"})
    m = new.merge(prev, on=["symbol", "qtr", "yr"])
    m["px"] = m["symbol"].map(close)
    m = m[(m["value"] - m["prev"]) / m["px"] >= BEAT_SURPRISE]
    return dict(zip(m["symbol"], m["first_seen"]))


def _unusual_letters(since: pd.Timestamp) -> dict[str, pd.Timestamp]:
    n = store.read_parquet(store.path("events", "psx_notices.parquet"))
    n = n[(n["announced_at"] >= since) & n["title"].str.contains("UNUSUAL", case=False, na=False)]
    out = {}
    for r in n.itertuples():
        for sym in re.findall(r"\(([A-Z0-9]{2,10})\)", r.title):
            out[sym] = max(out.get(sym, r.announced_at), r.announced_at)
    return out


def _kse30_removals(since: pd.Timestamp, symbols: set[str]) -> dict[str, pd.Timestamp]:
    """Outgoing KSE-30 constituents from PSX recomposition notices since `since`.
    Rows look like '1 NRL National Refinery Limited APL Attock Petroleum Limited'
    (2024) or '1 Ghandhara Industries Limited Bank Alfalah Limited' (2025+):
    incoming first, outgoing second; special recompositions list outgoing first."""
    import pdfplumber

    from mbf.psx.client import PSXClient

    n = store.read_parquet(store.path("events", "psx_notices.parquet"))
    n = n[(n["announced_at"] >= since) & n["title"].str.contains(r"KSE\W*30", case=False, regex=True)
          & n["title"].str.contains("COMPOSITION", case=False) & n["pdf_url"].str.endswith(".pdf", na=False)]
    out: dict[str, pd.Timestamp] = {}
    if n.empty:
        return out
    from mbf.research.rights import name_index
    names = {k: v for k, v in name_index().items() if v in symbols}
    cache = store.path("raw", "notices")
    cache.mkdir(parents=True, exist_ok=True)
    client = None
    for r in n.itertuples():
        f = cache / f"{r.doc_id}.pdf"
        try:
            if not f.exists():
                client = client or PSXClient()
                f.write_bytes(client.download(r.pdf_url))
            with pdfplumber.open(io.BytesIO(f.read_bytes())) as pdf:
                text = pdf.pages[0].extract_text() or ""
        except Exception as e:
            log.warning("KSE-30 notice %s unreadable: %s", r.pdf_url, e)
            continue
        special = re.search(r"SPECIAL", r.title, re.I)
        for line in text.splitlines():
            row = re.match(r"\s*\d{1,2}\s+(.*)$", line)
            if not row:
                continue
            row = row.group(1)
            if special:
                # "1 KSE30 <outgoing> <incoming>": only rows for KSE-30
                if not re.match(r"KSE\W*30\b", row, re.I):
                    continue
                row = re.sub(r"^KSE\W*30\s+", "", row, flags=re.I)
            sym = _outgoing(row, symbols, outgoing_first=bool(special), names=names)
            if sym:
                out[sym] = r.announced_at
    return out


def _outgoing(row: str, symbols: set[str], outgoing_first: bool, names: dict) -> str | None:
    """'NRL National Refinery Limited APL Attock Petroleum Limited' or
    'Ghandhara Industries Limited Bank Alfalah Limited' -> the outgoing ticker."""
    from mbf.research.rights import match_symbol

    m = re.match(r"(.+?\b(?:Limited|Ltd)\.?)\s+(.+)$", row)
    if not m:
        return None
    first, second = m.group(1), m.group(2)
    part = first if outgoing_first else second
    tok = re.match(r"([A-Z0-9]{2,8})\s", part)
    if tok and tok.group(1) in symbols:
        return tok.group(1)
    part = re.sub(r"^[A-Z0-9]{2,8}\s+(?=[A-Z][a-z])", "", part)     # drop an unknown ticker prefix
    sym = match_symbol(part, names)
    return sym if sym in symbols else None


def compute(feats_today: pd.DataFrame, asof: pd.Timestamp, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per (symbol, warning) active after the close of `asof`."""
    f = feats_today.set_index("symbol")
    rows = []
    i = sessions.searchsorted(asof)
    # ex-date in the last 3 sessions (cash dividend: factor in [0.85, 1))
    ca = store.read_parquet(store.path("prices", "corporate_actions.parquet"))
    recent = ca[ca["applied"] & (ca["date"] >= sessions[max(0, i - 2)]) & (ca["date"] <= asof)
                & (ca["factor"] < 1) & (ca["factor"] >= 0.85)]
    for r in recent.itertuples():
        rows.append((r.symbol, "after_ex_date", r.date))
    weak = f[(f["close_loc"] <= 0.15) & (f["r1"] <= -0.03)] if "r1" in f else f.iloc[0:0]
    rows += [(s, "weak_close", asof) for s in weak.index]
    spike = f[f["vol_ratio"] > 3]
    rows += [(s, "volume_spike", asof) for s in spike.index]
    for s, d in _results_beats(sessions[max(0, i - 2)], f["close"]).items():
        rows.append((s, "after_results_beat", d))
    since20 = sessions[max(0, i - 19)]
    for s, d in _unusual_letters(since20).items():
        rows.append((s, "unusual_movement_letter", d))
    try:
        for s, d in _kse30_removals(sessions[max(0, i - 5)], set(f.index)).items():
            rows.append((s, "leaving_kse30", d))
    except Exception as e:                                   # never let a parser stop the run
        log.warning("KSE-30 removals: %s", e)
    w = pd.DataFrame(rows, columns=["symbol", "warning", "since"])
    if w.empty:
        return w.assign(title=[], detail=[])
    w = w.drop_duplicates(["symbol", "warning"])
    w["title"] = w["warning"].map(lambda k: WARNINGS[k][0])
    w["detail"] = w["warning"].map(lambda k: WARNINGS[k][1])
    return w.reset_index(drop=True)
