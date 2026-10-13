"""One-time import of the old AKD pulls (legacy/akd_data/*.csv) into typed Parquet.

Used for two things only:
  * point-in-time fundamentals history (2018+) for backtests, which PSX does
    not offer in structured form;
  * an independent price/corporate-action series to validate PSX data against.
Nothing in the live pipeline depends on AKD.

Known AKD quirks (from the legacy research, see legacy/refresh.py header):
  * prices are a TOTAL-RETURN series (dividends and bonuses adjusted out);
  * the same payout is often filed twice under different type codes;
  * roe/roa/npm/div_yield are fractions, other ratios are plain;
  * unconsolidatedQuarterEpsYOY is only populated for 2018-19.
"""
from __future__ import annotations

import logging

import pandas as pd

from mbf import config, store

log = logging.getLogger(__name__)

JUNK = {"AAL", "EXCHANGE", "HUSS", "NAZC", "OPENFUND", "OTHER", "SGABL", "PSX"}


def _num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _dates(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def payout_events(a: pd.DataFrame) -> pd.DataFrame:
    """One economic event per (symbol, ex-date).

    Units, verified against PSX on 2026-10-13: `dividend` is RUPEES per share
    (OGDC 2026-10-08: 6.0 = the Rs 6 / 60% payout) while `bonus` and
    `rightIssue` are PERCENT (HICL 61.45 -> ratio 0.6194 on the ex-date). The
    legacy refresh.py divided `dividend` by 10, under-stating every dividend
    tenfold; do not reuse legacy/work/payout_events.parquet.
    The same payout is often filed twice under different type codes, so we
    collapse on (symbol, ex-date) with max(), never sum().
    """
    m = a["exDate"].notna() & ((a["dividend"].fillna(0) > 0) | (a["bonus"].fillna(0) > 0)
                               | (a["rightIssue"].fillna(0) > 0))
    ev = a.loc[m, ["symbol", "exDate", "date", "dividend", "bonus", "rightIssue", "rightPrice",
                   "book_closure_date_from", "book_closure_date_to", "announcementType"]]
    ev = (ev.groupby(["symbol", "exDate"], as_index=False)
            .agg(div_rs=("dividend", "max"), bonus_pct=("bonus", "max"),
                 right_pct=("rightIssue", "max"), right_px=("rightPrice", "max"),
                 announce_date=("date", "min"), bc_from=("book_closure_date_from", "min"),
                 bc_to=("book_closure_date_to", "max"), n_filings=("announcementType", "size"))
            .rename(columns={"exDate": "ex_date"}))
    ev["div_rs"] = ev["div_rs"].fillna(0.0)
    ev["bonus_r"] = ev["bonus_pct"].fillna(0.0) / 100.0
    ev["right_r"] = ev["right_pct"].fillna(0.0) / 100.0
    return ev.drop(columns=["bonus_pct", "right_pct"])


def run(src=None) -> dict:
    src = src or config.LEGACY_AKD_DIR
    out = {}

    a = pd.read_csv(src / "mbf_announcements.csv", low_memory=False)
    a = _dates(a, ["date", "periodEndDate", "previousPeriodEndDate", "exDate",
                   "book_closure_date_from", "book_closure_date_to", "heldDate"])
    a = _num(a, ["unconsolidatedSales", "unconsolidatedPat", "unconsolidatedQuarterEps",
                 "unconsolidatedQuarterEpsYOY", "dividend", "bonus", "rightIssue", "rightPrice"])
    a = a.dropna(subset=["symbol", "date"])
    a = a[~a["symbol"].isin(JUNK)]
    for c in ("announcementType", "title", "revised"):
        if c in a.columns:
            a[c] = a[c].astype("string")
    out["announcements"] = a

    f = pd.read_csv(src / "mbf_fundamentals.csv", low_memory=False)
    f = _dates(f, ["period_end"])
    f = _num(f, ["value", "year"])
    out["fundamentals"] = f.dropna(subset=["period_end", "value"])

    s = pd.read_csv(src / "mbf_statements.csv", low_memory=False)
    s = _dates(s, ["period_end"])
    s = _num(s, ["value", "year"])
    s["quarter"] = s["quarter"].astype("string")
    out["statements"] = s.dropna(subset=["period_end", "value"])

    p = pd.read_csv(src / "mbf_profiles.csv")
    p = p[~p["symbol"].isin(JUNK)]
    out["profiles"] = _num(p, ["par_value", "employees", "status"])

    px = pd.read_csv(src / "mbf_prices.csv")
    px = _dates(px, ["date"])
    px["date"] = px["date"].dt.normalize()          # AKD stamps bars with a time (16:00:00)
    px = _num(px, ["open", "high", "low", "close", "volume"]).drop(columns=["value"], errors="ignore")
    out["prices_total_return"] = px[~px["symbol"].isin(JUNK)].dropna(subset=["date", "close"])

    out["payout_events"] = payout_events(a)

    for name, df in out.items():
        store.write_parquet(df.reset_index(drop=True), store.path("seed", "akd", f"{name}.parquet"))
        log.info("akd seed: %-20s %s rows", name, f"{len(df):,}")
    return {k: len(v) for k, v in out.items()}
