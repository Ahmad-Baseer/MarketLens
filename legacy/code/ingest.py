"""
Multi Beggar Finder — Stage 1: ingest raw AKD exports into a clean panel.

KEY FINDING that shapes this file
---------------------------------
AKD's /daily/{SYM} series is ALREADY fully back-adjusted for cash dividends
AND bonus issues. Measured across 2021-09..2026-06:

    cash-dividend ex-dates (n=1611): actual return -0.21%  vs  mechanical -5.18%
    bonus ex-dates          (n= 161): actual return -0.10%  vs  mechanical -16.98%

i.e. the mechanical drop has been removed. So:
  * we do NOT apply our own bonus/rights adjustment (that would double-adjust)
  * the series is a TOTAL-RETURN series, not the price a trader sees on screen

Because the user wants dividends to be incidental upside and NOT a decision
driver, we carry two return concepts:
  * tr_close   : AKD's adjusted close  -> total return (price + payouts)
  * px_close   : de-adjusted close      -> price-only, what the chart shows
The target/stop logic runs on px_close. tr_close is reported alongside so a
dividend landing in the window shows up as a bonus, never as the reason a
candidate was picked.

De-adjustment: AKD's factor is piecewise-constant, stepping only at ex-dates.
We rebuild the step function from the announcement feed (dividend/bonus/rights
with ex-dates) and multiply it back out, anchored so that the MOST RECENT
segment equals AKD's own values (recent bars are raw: 99.4% of 2026 closes sit
exactly on a 2-decimal tick).

Other data quirks handled here
------------------------------
  * `value` column is 100% zero      -> traded value computed as close*volume
  * 810 rows have <=0 prices (PHDL 805, ICCT 5) -> dropped
  * 13,751 rows (2.4%) have close outside [low,high] -> OHLC clamped, not dropped
  * profiles.status: 1=active(553), 0=inactive(67), NaN(21) -> survivorship flag
  * year_end has typos ('Dec','Decemeber') -> normalised
"""
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("/home/claude/mbf/raw")
WORK = Path("/home/claude/mbf/work")
WORK.mkdir(parents=True, exist_ok=True)

JUNK_SYMBOLS = {"AAL", "EXCHANGE", "HUSS", "NAZC", "OPENFUND", "OTHER", "SGABL"}

MONTH_FIX = {
    "Dec": "December", "Decemeber": "December", "Jun": "June",
    "Sep": "September", "Sept": "September", "Mar": "March",
}


def _num(s):
    return pd.to_numeric(s, errors="coerce")


# ---------------------------------------------------------------- announcements
def load_announcements() -> pd.DataFrame:
    df = pd.read_csv(RAW / "mbf_announcements.csv", low_memory=False)
    for c in ("date", "periodEndDate", "previousPeriodEndDate", "exDate",
              "book_closure_date_from", "book_closure_date_to", "heldDate"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ("unconsolidatedSales", "unconsolidatedPat", "unconsolidatedQuarterEps",
              "unconsolidatedQuarterEpsYOY", "dividend", "bonus", "rightIssue", "rightPrice"):
        if c in df.columns:
            df[c] = _num(df[c])
    df = df.dropna(subset=["symbol", "date"])
    df = df[~df["symbol"].isin(JUNK_SYMBOLS)]
    df["ann_family"] = df["announcementType"].astype(str).str[:4]
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def payout_events(ann: pd.DataFrame) -> pd.DataFrame:
    """Every ex-date at which AKD's adjustment factor steps.

    dividend / bonus / rightIssue are reported as PERCENT OF PAR (Rs 10),
    which is the PSX convention: dividend=13 means Rs 1.30/share.
    """
    m = ann["exDate"].notna() & (
        (ann["dividend"].fillna(0) > 0)
        | (ann["bonus"].fillna(0) > 0)
        | (ann["rightIssue"].fillna(0) > 0)
    )
    ev = ann.loc[m, ["symbol", "exDate", "date", "dividend", "bonus",
                     "rightIssue", "rightPrice", "announcementType"]].copy()
    ev = ev.rename(columns={"exDate": "ex_date", "date": "announce_date"})
    ev["div_rs"] = ev["dividend"].fillna(0) / 10.0        # % of Rs10 par -> Rs/share
    ev["bonus_r"] = ev["bonus"].fillna(0) / 100.0
    ev["right_r"] = ev["rightIssue"].fillna(0) / 100.0
    ev["right_px"] = ev["rightPrice"]

    # One ECONOMIC event per (symbol, ex_date). The same payout is often filed
    # under two different announcementType codes (e.g. a board decision and the
    # subsequent confirmation), and de-duplicating on the type code leaves both
    # rows in — which applies the adjustment factor twice. Verified on
    # AABS 2023-09-21: implied k came out 0.9883 = 0.9941^2 instead of 0.9941.
    # Take the max of each component so a partially-populated duplicate cannot
    # dilute the real figure.
    ev = (ev.sort_values(["symbol", "ex_date"])
            .groupby(["symbol", "ex_date"], as_index=False)
            .agg(div_rs=("div_rs", "max"),
                 bonus_r=("bonus_r", "max"),
                 right_r=("right_r", "max"),
                 right_px=("right_px", "max"),
                 announce_date=("announce_date", "min"),
                 n_filings=("announcementType", "size"))
            .reset_index(drop=True))
    dup = int((ev["n_filings"] > 1).sum())
    print(f"  collapsed {dup:,} ex-dates that had multiple filings of the same payout")
    return ev


# ---------------------------------------------------------------------- prices
def load_prices() -> pd.DataFrame:
    df = pd.read_csv(RAW / "mbf_prices.csv")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = _num(df[c])
    df = df.drop(columns=["value"], errors="ignore")     # 100% zero, useless
    df = df[~df["symbol"].isin(JUNK_SYMBOLS)]
    df = df.dropna(subset=["date", "close"])

    n0 = len(df)
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    print(f"  dropped {n0 - len(df):,} rows with non-positive prices")

    # clamp OHLC so the bar is internally consistent; adjustment rounding makes
    # ~2.4% of bars violate close in [low, high]
    lo = df[["open", "high", "low", "close"]].min(axis=1)
    hi = df[["open", "high", "low", "close"]].max(axis=1)
    nviol = int(((df["low"] > lo) | (df["high"] < hi)).sum())
    df["low"], df["high"] = lo, hi
    print(f"  clamped {nviol:,} OHLC-inconsistent bars")

    df = df.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"], keep="last")
    df["traded"] = (df["volume"].fillna(0) > 0).astype("int8")
    df["turnover"] = df["close"] * df["volume"].fillna(0)   # `value` was all zeros
    return df.reset_index(drop=True)


def deadjust(px: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Rebuild a price-only ('what the chart showed') series from AKD's
    total-return series.

    AKD's adjusted close A(t) relates to the raw close R(t) by a
    piecewise-constant factor f(t) that steps at each ex-date:
        A(t) = R(t) * f(t),  f(t) = prod over events e with ex_date > t of k_e
    with, for an event on cum price C:
        cash dividend D   ->  k = (C - D) / C
        bonus b           ->  k = 1 / (1 + b)
        rights r at P     ->  k = ((C + r*P) / (1 + r)) / C
    The newest segment has f = 1 (recent bars are raw), so R(t) = A(t) / f(t).
    """
    px = px.sort_values(["symbol", "date"]).copy()
    px["deadj_f"] = 1.0

    ev = ev[(ev["div_rs"] > 0) | (ev["bonus_r"] > 0) | (ev["right_r"] > 0)]
    ev_by_sym = {s: g.sort_values("ex_date") for s, g in ev.groupby("symbol", sort=False)}

    out = []
    for sym, g in px.groupby("symbol", sort=False):
        g = g.sort_values("date").copy()
        events = ev_by_sym.get(sym)
        if events is None or events.empty:
            out.append(g)
            continue

        adj_close = g.set_index("date")["close"]
        f = pd.Series(1.0, index=g.index)

        # walk events newest -> oldest, accumulating the factor for earlier bars
        for _, e in events.iloc[::-1].iterrows():
            ex = e["ex_date"]
            prior = adj_close[adj_close.index < ex]
            if prior.empty:
                continue
            C = float(prior.iloc[-1])          # cum price in ADJUSTED space
            if C <= 0:
                continue
            k = 1.0
            D = float(e["div_rs"] or 0)
            if D > 0 and D < C:
                k *= (C - D) / C
            b = float(e["bonus_r"] or 0)
            if b > 0:
                k *= 1.0 / (1.0 + b)
            r = float(e["right_r"] or 0)
            P = e["right_px"]
            if r > 0 and pd.notna(P):
                k *= ((C + r * float(P)) / (1.0 + r)) / C
            if k > 0 and k != 1.0:
                f.loc[g["date"] < ex] *= k

        g["deadj_f"] = f.values
        out.append(g)

    px = pd.concat(out).sort_values(["symbol", "date"])
    # price-only ("what the chart showed") vs total-return (AKD as given)
    for c in ("open", "high", "low", "close"):
        px[f"tr_{c}"] = px[c]
        px[f"px_{c}"] = px[c] / px["deadj_f"]
    n = int((px["deadj_f"] != 1.0).sum())
    print(f"  de-adjusted {n:,} bars ({n/len(px):.1%}) across "
          f"{px.loc[px['deadj_f'] != 1.0, 'symbol'].nunique()} symbols")
    return px.reset_index(drop=True)


# -------------------------------------------------------------------- profiles
def load_profiles() -> pd.DataFrame:
    df = pd.read_csv(RAW / "mbf_profiles.csv")
    df = df[~df["symbol"].isin(JUNK_SYMBOLS)]
    df["year_end"] = df["year_end"].replace(MONTH_FIX)
    df["active"] = df["status"].map({1.0: True, 0.0: False})
    return df[["symbol", "name", "sector_code", "sector_name", "active",
               "year_end", "par_value"]].reset_index(drop=True)


def load_statements() -> pd.DataFrame:
    df = pd.read_csv(RAW / "mbf_statements.csv", low_memory=False)
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df["value"] = _num(df["value"])
    df = df[~df["symbol"].isin(JUNK_SYMBOLS)]
    return df.dropna(subset=["symbol", "period_end", "field_key"]).reset_index(drop=True)


def main():
    print("announcements ...", flush=True)
    ann = load_announcements()
    ev = payout_events(ann)
    print(f"  {len(ann):,} rows, {ann['symbol'].nunique()} symbols, "
          f"{ann['date'].min().date()} -> {ann['date'].max().date()}")
    print(f"  {len(ev):,} payout/ex-date events")

    print("prices ...", flush=True)
    px = load_prices()
    px = deadjust(px, ev)
    print(f"  {len(px):,} bars, {px['symbol'].nunique()} symbols, "
          f"{px['date'].min().date()} -> {px['date'].max().date()}")

    print("profiles ...", flush=True)
    prof = load_profiles()
    vc = prof["active"].value_counts(dropna=False)
    print(f"  {len(prof)} symbols, {prof['sector_name'].nunique()} sectors, "
          f"active={int(vc.get(True, 0))} inactive={int(vc.get(False, 0))} "
          f"unknown={int(prof['active'].isna().sum())}")

    print("statements ...", flush=True)
    st = load_statements()
    print(f"  {len(st):,} rows, {st['symbol'].nunique()} symbols, "
          f"{st['field_key'].nunique()} fields")

    px.to_parquet(WORK / "prices.parquet", index=False)
    ann.to_parquet(WORK / "announcements.parquet", index=False)
    ev.to_parquet(WORK / "payout_events.parquet", index=False)
    prof.to_parquet(WORK / "profiles.parquet", index=False)
    st.to_parquet(WORK / "statements.parquet", index=False)
    print("\nwrote parquet ->", WORK)


if __name__ == "__main__":
    main()
