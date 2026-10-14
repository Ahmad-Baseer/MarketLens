"""Rights issues: announcement, run-up to ex-rights, and after ex-rights.

Events come from two sources:
  * PSX notices: "<SYM> | <Company> - Issuance of N% Right Shares at ..." (2009-2016)
    and "Commencement of Trading in the Unpaid Rights of <Company>" (2010-2026).
    Both appear around the ex-rights date, so they date the ex-date, not the decision.
  * AKD seed (2018+): rights ratio, price and the decision date (usually filed
    with the financial results).
The ex-rights session is taken from PSX's own LDCP adjustment (corporate_actions),
so every event is dated by what actually happened on the exchange.
"""
from __future__ import annotations

import difflib
import re

import numpy as np
import pandas as pd

from mbf import store
from mbf.adjust import DEBT_RE
from mbf.research.events import _sessions, snap_to_session

STOP = {"limited", "ltd", "the", "co", "company", "corporation", "corp", "inc", "plc", "pvt",
        "private", "m", "s", "ms"}
DECISION_RE = re.compile(r"right\s+(?:shares?|issue|certificates?)|issu\w*\s+of\s+(?:preference\s+)?right",
                         re.I)
UNPAID_RE = re.compile(r"unpaid\s+(?:preference\s+)?rights?\s+(?:of\s+)?(?:m/?s\.?\s*)?(.+)$", re.I)


def norm(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(w for w in s.split() if w not in STOP)


def name_index() -> dict[str, str]:
    """normalised company name -> symbol, from every name source we hold."""
    out: dict[str, str] = {}
    for p, sym, nm in [(("ref", "symbols.parquet"), "symbol", "name"),
                       (("ref", "market_watch.parquet"), "symbol", "name")]:
        df = store.read_parquet(store.path(*p))
        for s, n in zip(df[sym], df[nm]):
            if (isinstance(n, str) and isinstance(s, str) and "-" not in s
                    and not re.search(DEBT_RE, s)):
                out.setdefault(norm(n), s)
    return out


def match_symbol(name: str, idx: dict[str, str], cutoff: float = 0.88) -> str | None:
    k = norm(name)
    if k in idx:
        return idx[k]
    best = difflib.get_close_matches(k, list(idx), n=1, cutoff=cutoff)
    return idx[best[0]] if best else None


def _pct(title: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", title)
    return float(m.group(1)) / 100 if m else np.nan


def psx_notices() -> pd.DataFrame:
    """Rights decisions and unpaid-rights trading notices from PSX's own notices."""
    n = store.read_parquet(store.path("events", "psx_notices.parquet"))
    n = n[~n["title"].str.contains("REVOKED|TRE\\b|ENTITLEMENT|Other than Right|DRAFT OFFER",
                                   case=False, regex=True)]
    idx = name_index()
    rows = []
    for r in n.itertuples():
        t = re.sub(r"\s+", " ", r.title).strip()
        um = UNPAID_RE.search(t)
        if um:
            name = re.sub(r"\s*(?:limited|ltd)\.?\s*$", " Limited", um.group(1), flags=re.I)
            rows.append({"kind": "unpaid_trading", "date": r.announced_at, "title": t,
                         "symbol": match_symbol(name, idx), "name": name, "ratio": np.nan})
            continue
        if DECISION_RE.search(t) and not re.search(r"trading in a scrip|commencement", t, re.I):
            sym = None
            m = re.match(r"^([A-Z0-9]{2,8})\s*[|:]\s*(.+)$", t)
            body = m.group(2) if m else t
            if m:
                sym = m.group(1)
            name = re.split(r"\s+-\s+|\s*-\s*Issu|\s+\d+(?:\.\d+)?\s*%|\s*\(", body, maxsplit=1)[0]
            sym = sym or match_symbol(name, idx)
            rows.append({"kind": "issue_notice", "date": r.announced_at, "title": t, "symbol": sym,
                         "name": name.strip(), "ratio": _pct(t)})
    return pd.DataFrame(rows)


def _factor_events() -> pd.DataFrame:
    ca = store.read_parquet(store.path("prices", "corporate_actions.parquet"))
    return ca[ca["applied"]][["symbol", "date", "factor"]].sort_values("date")


def events(f: pd.DataFrame) -> pd.DataFrame:
    """One row per rights issue: symbol, ann_date (decision, may be NaT), x_date
    (PSX ex-rights session), ratio, price, source."""
    fe = _factor_events()
    out = []

    # --- AKD 2018+: decision date + ex-date matched to PSX's adjustment
    ak = store.read_parquet(store.path("seed", "akd", "payout_events.parquet"))
    ak = ak[ak["right_r"] > 0]
    m = ak.merge(fe.rename(columns={"date": "x_date"}), on="symbol")
    m = m[(m["x_date"] - m["ex_date"]).abs() <= pd.Timedelta(days=10)]
    m["d"] = (m["x_date"] - m["ex_date"]).abs()
    m = m.sort_values("d").drop_duplicates(["symbol", "ex_date"])
    for r in m.itertuples():
        out.append({"symbol": r.symbol, "ann_date": r.announce_date, "x_date": r.x_date,
                    "ratio": r.right_r, "price": r.right_px, "factor": r.factor,
                    "with_cash_div": r.div_rs > 0, "source": "akd"})

    # --- PSX notices. Both kinds are published around the ex-date, not at the board
    #     decision (verified 2014-2016: "Issuance of N% Right Shares" appears 0-10 days
    #     after PSX's LDCP adjustment), so they date the ex-rights session only.
    pn = psx_notices().dropna(subset=["symbol"])
    for r in pn.itertuples():
        e = fe[fe["symbol"] == r.symbol]
        d = r.date.normalize()
        c = e[(e["date"] <= d + pd.Timedelta(days=10)) & (e["date"] >= d - pd.Timedelta(days=45))]
        if len(c):
            k = (c["date"] - d).abs().argmin() if r.kind == "issue_notice" else len(c) - 1
            out.append({"symbol": r.symbol, "ann_date": pd.NaT, "x_date": c["date"].iloc[k],
                        "ratio": r.ratio, "price": np.nan, "factor": c["factor"].iloc[k],
                        "with_cash_div": np.nan, "source": f"psx_{r.kind}"})
    ev = pd.DataFrame(out)
    # merge sources per (symbol, ex-date): prefer AKD, then a PSX decision, then unpaid notice
    pri = ev["source"].map({"akd": 0, "psx_issue_notice": 1, "psx_unpaid_trading": 2})
    ev = ev.assign(pri=pri).sort_values(["symbol", "x_date", "pri"])
    first = ev.groupby(["symbol", "x_date"], as_index=False).first()
    first["sources"] = ev.groupby(["symbol", "x_date"])["source"].agg(
        lambda s: "+".join(sorted(set(s)))).to_numpy()
    first = first.drop(columns=["pri"])

    s = _sessions(f)
    pos = pd.Series(np.arange(len(s)), index=s)
    first["x_idx"] = first["x_date"].map(pos)
    first["ann_idx"] = snap_to_session(first["ann_date"], s, 0).map(pos)
    # decisions are often filed with results during/after market hours: act from the next close
    first = first.dropna(subset=["x_idx"])
    first = first[first["x_date"] >= pd.Timestamp("2013-11-04")]
    return first.reset_index(drop=True)
