"""Data-quality report: is the PSX data complete, and does it agree with an
independent source (the legacy AKD pulls)? Writes reports/data_quality.md."""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from mbf import config, store
from mbf.adjust import equities, non_equity_symbols

log = logging.getLogger(__name__)


def _md(df: pd.DataFrame, floatfmt: str = "{:,.2f}") -> str:
    if df is None or df.empty:
        return "_(none)_\n"
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False):
        cells = []
        for v in row:
            if isinstance(v, (float, np.floating)):
                cells.append("" if pd.isna(v) else floatfmt.format(v))
            elif isinstance(v, pd.Timestamp):
                cells.append(str(v.date()))
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def _pct(x) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{100 * x:.1f}%"


def coverage(raw: pd.DataFrame, daily: pd.DataFrame) -> tuple[str, dict]:
    trading, holidays = store.fetched_days()
    weekdays = pd.bdate_range(config.HISTORY_START, max(trading)).date if trading else []
    missing = sorted(set(weekdays) - set(trading) - set(holidays))
    eq = equities(raw, non_equity_symbols())
    per_day = eq.groupby("date").agg(listed=("symbol", "size"),
                                     traded=("volume", lambda v: int((v > 0).sum())))
    by_year = per_day.groupby(per_day.index.year).agg(
        trading_days=("listed", "size"), median_listed=("listed", "median"),
        median_traded=("traded", "median")).reset_index(names="year")

    idx = store.read_parquet(store.path("indices", "eod.parquet"))
    cal_note = "index series not available"
    cal = {}
    if not idx.empty:
        k = set(idx.loc[idx["symbol"] == "KSE100", "date"].dt.date)
        lo = min(k)
        ours = {d for d in trading if d >= lo}
        cal = {"in_index_not_ours": sorted(k - ours), "in_ours_not_index": sorted(ours - k)}
        cal_note = (f"since {lo}: {len(k)} KSE-100 sessions vs {len(ours)} of ours; "
                    f"{len(cal['in_index_not_ours'])} index days missing from our data, "
                    f"{len(cal['in_ours_not_index'])} extra days in ours")
    modern = [d for d in trading if d >= config.MODERN_FROM]
    s = [f"- Range: **{min(trading)} -> {max(trading)}**, {len(trading):,} trading days, "
         f"{len(holidays):,} weekday holidays/closures detected",
         f"- Research-grade (modern) era: **{config.MODERN_FROM} -> {max(trading)}**, "
         f"{len(modern):,} trading days — see section 7",
         f"- Weekdays with no file (fetch failed, needs a retry): **{len(missing)}**"
         + (f" — e.g. {', '.join(map(str, missing[:10]))}" if missing else ""),
         f"- Calendar check vs PSX's KSE-100 series: {cal_note}",
         f"- Equity rows: {len(eq):,} raw, {len(daily):,} after cleaning; "
         f"{eq['symbol'].nunique():,} distinct equity symbols ever listed", "",
         "Per year (equities only: futures, bonds, T-bills, sukuks and index codes excluded):", "",
         _md(by_year, "{:,.0f}")]
    if cal.get("in_index_not_ours"):
        s += [f"Index sessions missing from our data: {', '.join(map(str, cal['in_index_not_ours'][:20]))}", ""]
    return "\n".join(s), {"missing": len(missing), **{k: len(v) for k, v in cal.items()}}


def vs_akd_returns(daily: pd.DataFrame) -> tuple[str, dict]:
    akd = store.read_parquet(store.path("seed", "akd", "prices_total_return.parquet"))
    if akd.empty:
        return "_AKD seed not imported_\n", {}
    akd = akd.sort_values(["symbol", "date"])
    akd["akd_prev"] = akd.groupby("symbol")["date"].shift(1)
    akd["akd_ret"] = akd["close"] / akd.groupby("symbol")["close"].shift(1) - 1
    d = daily[["symbol", "date", "ret", "close", "traded"]].copy()
    d["prev"] = d.groupby("symbol")["date"].shift(1)
    m = d.merge(akd[["symbol", "date", "akd_prev", "akd_ret"]], on=["symbol", "date"], how="inner")
    m = m[(m["prev"] == m["akd_prev"]) & m["ret"].notna() & m["akd_ret"].notna()]
    diff = (m["ret"] - m["akd_ret"]).abs()
    m["ok01"], m["ok05"] = diff < 0.001, diff < 0.005
    by_year = (m.groupby(m["date"].dt.year)
                .agg(symbol_days=("ok01", "size"), within_0_1pct=("ok01", "mean"),
                     within_0_5pct=("ok05", "mean")).reset_index(names="year"))
    worst = (m.assign(diff=diff).sort_values("diff", ascending=False)
              .head(12)[["symbol", "date", "close", "ret", "akd_ret", "diff"]])
    res = {"n": len(m), "within_0_1pct": m["ok01"].mean(), "within_0_5pct": m["ok05"].mean()}
    s = [f"Daily total returns compared on {len(m):,} symbol-days where both sources have the "
         f"same previous session ({m['date'].min().date()} -> {m['date'].max().date()}).",
         f"- Agree within 0.1%: **{_pct(res['within_0_1pct'])}**; within 0.5%: "
         f"**{_pct(res['within_0_5pct'])}**", "", _md(by_year, "{:,.3f}"),
         "Largest disagreements (either source may be the wrong one):", "",
         _md(worst, "{:,.4f}")]
    return "\n".join(s), res


def vs_akd_events(events: pd.DataFrame, daily: pd.DataFrame) -> tuple[str, dict]:
    ak = store.read_parquet(store.path("seed", "akd", "payout_events.parquet"))
    if ak.empty:
        return "_AKD payout events not available_\n", {}
    last = daily["date"].max()
    first_px = daily.groupby("symbol")["date"].min()
    ak = ak[(ak["ex_date"] >= "2018-01-01") & (ak["ex_date"] <= last)
            & ((ak["div_rs"] > 0) | (ak["bonus_r"] > 0) | (ak["right_r"] > 0))].copy()
    ak = ak[ak["symbol"].map(first_px).lt(ak["ex_date"])]          # we have prices before it
    ev = events[events["applied"]][["symbol", "date", "factor", "implied_cash", "prev_close"]]

    # trading-day calendar to measure offsets in sessions, not calendar days
    sessions = pd.DatetimeIndex(sorted(daily["date"].unique()))

    def sess(ts):
        return sessions.searchsorted(ts)

    m = ak.merge(ev, on="symbol", how="left", suffixes=("", "_psx"))
    m = m[(m["date"] - m["ex_date"]).abs() <= pd.Timedelta(days=10)]
    m["off"] = [sess(a) - sess(b) for a, b in zip(m["date"], m["ex_date"])]
    m = m[m["off"].abs() <= 5]
    best = (m.assign(aoff=m["off"].abs()).sort_values("aoff")
             .drop_duplicates(["symbol", "ex_date"]))
    found = ak.merge(best[["symbol", "ex_date", "off", "factor", "implied_cash", "prev_close"]],
                     on=["symbol", "ex_date"], how="left")
    found["found"] = found["off"].notna()
    recall = found["found"].mean()
    offs = found.loc[found["found"], "off"].value_counts().sort_index()
    offs = offs.rename("events").reset_index().rename(columns={"off": "PSX date minus AKD ex-date (sessions)"})
    cash = found[found["found"] & (found["bonus_r"] == 0) & (found["right_r"] == 0) & (found["div_rs"] > 0)]
    agree = ((cash["implied_cash"] - cash["div_rs"]).abs() <= 0.02 * cash["div_rs"] + 0.011)
    by_kind = pd.DataFrame({
        "kind": ["cash dividend", "bonus", "rights"],
        "AKD events": [int(((found.div_rs > 0) & (found.bonus_r == 0) & (found.right_r == 0)).sum()),
                       int((found.bonus_r > 0).sum()), int((found.right_r > 0).sum())],
        "found in PSX LDCP": [
            found.loc[(found.div_rs > 0) & (found.bonus_r == 0) & (found.right_r == 0), "found"].mean(),
            found.loc[found.bonus_r > 0, "found"].mean(),
            found.loc[found.right_r > 0, "found"].mean()]})
    missed = found[~found["found"]].sort_values("ex_date", ascending=False).head(12)[
        ["symbol", "ex_date", "div_rs", "bonus_r", "right_r"]]
    ours_2018 = ev[ev["date"] >= "2018-01-01"]
    res = {"akd_events": len(found), "recall": recall, "cash_amount_agree": agree.mean(),
           "psx_events_2018": len(ours_2018)}
    s = [f"AKD payout events since 2018 with PSX prices on both sides: **{len(found):,}**. "
         f"Found as an LDCP adjustment within ±5 sessions: **{_pct(recall)}**.",
         f"- Cash dividends: PSX-implied amount matches AKD's within 2%: **{_pct(agree.mean())}** "
         f"of {len(cash):,}",
         f"- PSX detected {len(ours_2018):,} adjustments since 2018 in total (AKD's file also misses some, "
         f"e.g. rights and splits).", "", _md(by_kind, "{:.1%}"),
         "Where PSX puts the event relative to AKD's ex-date:", "", _md(offs, "{:,.0f}"),
         "Most recent AKD events with no PSX adjustment nearby:", "", _md(missed, "{:,.3f}")]
    return "\n".join(s), res


def suspicious_moves(daily: pd.DataFrame, events: pd.DataFrame) -> tuple[str, dict]:
    d = daily[daily["traded"]]
    big = d[d["suspect"]]
    by_year = (big.groupby(big["date"].dt.year).size().rename_axis("year")
                  .rename("suspect rows").reset_index())
    mod = d[d["modern"]]
    modern_line = (f"Modern era only: **{int(mod['suspect'].sum()):,}** of {len(mod):,} traded rows "
                   f"({mod['suspect'].mean():.4%}).")
    worst = big.reindex(big["ret"].abs().sort_values(ascending=False).index).head(12)[
        ["symbol", "date", "ldcp", "close", "volume", "ret"]]
    skipped = events[~events["applied"]]
    s = [f"Rows flagged `suspect` (daily move beyond any circuit breaker PSX has used: "
         f"> max(30%, Rs 1.5)): **{len(big):,}** of {len(d):,} traded rows ({len(big) / max(len(d), 1):.3%}). "
         f"Mostly thinly traded small stocks in 2000-2005; research excludes them. {modern_line}", "",
         _md(by_year, "{:,.0f}"), "Largest:", "", _md(worst, "{:,.4f}"),
         f"LDCP gaps not applied as corporate actions: {len(skipped):,} "
         f"({skipped['kind_guess'].value_counts().to_dict()})", ""]
    return "\n".join(s), {"suspect_rows": len(big)}


KNOWN_LIMITS = """\
- **Research-grade data starts 2013-11-04 (`config.MODERN_FROM`).** Before it PSX's "open" is a
  copy of the previous close on ~90% of rows, and LDCP is never adjusted for dividends,
  bonuses or rights (zero adjustments 2012Q1-2013Q3; 35 in 2013Q4, ~80 per quarter after).
  Older rows are kept with `modern = False`: opens are unknown, returns are price-only, and
  every ex-date shows as a fake drop. Use them for long-run market context only — never to
  backtest a 1-5 day signal.
- **About 20 symbols in 2016** have a blank LDCP for most of the year (exchange-merger period);
  their returns fall back to the previous close, so their 2016 ex-dates are unadjusted.
- **Aug 27 - Dec 15, 2008: market floor.** Almost nothing traded and positions could not be
  exited (`config.MARKET_FREEZE`). Backtests must treat it as untradeable, not as flat.
- **PSX occasionally answers a trading day with an empty table.** Empty days are retried
  before being marked as holidays, recent holidays are re-checked on every update, and the
  KSE-100 calendar check above catches any that slip through.
- **Missed corporate actions are rare:** of ~3,000 AKD payout events since 2018, about 18 show
  a price drop that PSX's LDCP did not adjust for (~1 in 100,000 daily returns).
- **AKD's ex-dates are usually one session late** relative to PSX (see section 3); PSX's LDCP
  is the reference, AKD is only a cross-check.
- **No official index before 2021-10** from PSX; the cap-weighted proxy (section 5) stands in.
"""


def market_proxy_check() -> tuple[str, dict]:
    from mbf import market
    px = store.read_parquet(store.path("indices", "market_proxy.parquet"))
    if px.empty:
        return "_market proxy not built (run `mbf adjust`)_\n", {}
    c = market.compare_with_kse100(px)
    if not c:
        return "_KSE-100 series not available_\n", {}
    cov = (px.groupby(px["date"].dt.year)
             .agg(cw_coverage=("cw_coverage", "median"), cw_names=("cw_names", "median"))
             .reset_index(names="year"))
    s = [f"Two proxies, {px['date'].min().date()} -> {px['date'].max().date()}: **CW** = top-100 by "
         f"estimated free-float market cap, cap-weighted (KSE-100's own method); **EW** = 100 most-traded "
         f"stocks, equal-weighted (the 'average liquid stock'). Compared with PSX's KSE-100 on "
         f"{c['days']:,} common days:",
         f"- Daily correlation: CW **{c['corr_ret_cw']:.3f}** (beta {c['beta_ret_cw']:.2f}), "
         f"EW **{c['corr_ret_ew']:.3f}** (beta {c['beta_ret_ew']:.2f})",
         f"- Cumulative over the overlap: KSE-100 {c['cum_kse']:+.1%} (price only); CW "
         f"{c['cum_ret_cw']:+.1%}, EW {c['cum_ret_ew']:+.1%} (both include dividends)", "",
         "CW coverage by year — share of traded value in names with a known share count "
         "(falls in early years as since-delisted companies drop out):", "",
         _md(cov, "{:,.2f}")]
    return "\n".join(s) + "\n", c


def other_tables() -> str:
    lines = []
    sym = store.read_parquet(store.path("ref", "symbols.parquet"))
    if not sym.empty:
        eqm = ~sym["is_debt"] & ~sym["is_etf"] & ~sym["is_future"]
        lines.append(f"- Symbols: {len(sym):,} listed, {int(eqm.sum()):,} equities, "
                     f"{sym.loc[eqm, 'sector'].nunique()} sectors")
    idx = store.read_parquet(store.path("indices", "eod.parquet"))
    if not idx.empty:
        g = idx.groupby("symbol")["date"].agg(["min", "max", "size"])
        lines.append("- Indices: " + "; ".join(f"{k} {r['min'].date()}->{r['max'].date()} ({r['size']})"
                                                for k, r in g.iterrows()))
    snaps = sorted((config.DATA_DIR / "fundamentals" / "snapshots").glob("*"))
    if snaps:
        sd = snaps[-1]
        info = pd.read_parquet(sd / "info.parquet")
        q = pd.read_parquet(sd / "quote.parquet")
        eqp = pd.read_parquet(sd / "equity.parquet")
        f = pd.read_parquet(sd / "financials.parquet")
        n = len(info)
        has = lambda kind, item: f[(f.kind == kind) & (f.item == item)]["symbol"].nunique() / max(n, 1)
        lines.append(f"- Fundamentals snapshot {sd.name}: {n} companies; P/E (TTM) present "
                     f"{_pct(q['pe_ttm'].notna().mean())}, market cap {_pct(eqp['market_cap_000'].notna().mean())}, "
                     f"annual EPS {_pct(has('annual', 'EPS'))}, quarterly EPS {_pct(has('quarterly', 'EPS'))}, "
                     f"sales {_pct(has('annual', 'Sales'))} (banks report mark-up instead)")
    rep = store.read_parquet(store.path("fundamentals", "reports.parquet"))
    if not rep.empty:
        lines.append(f"- Report PDFs listed: {len(rep):,} across {rep['symbol'].nunique()} companies "
                     f"({(rep['report_type'] == 'Quarterly').sum():,} quarterly, "
                     f"{(rep['report_type'] == 'Annual').sum():,} annual)")
    pay = store.read_parquet(store.path("events", "payouts.parquet"))
    if not pay.empty:
        lines.append(f"- Payouts: {len(pay):,} components, {pay['announced_at'].min().date()} -> "
                     f"{pay['announced_at'].max().date()}; unparsed kind: {_pct(pay['kind'].isna().mean())}")
    ann = store.read_parquet(store.path("events", "announcements.parquet"))
    if not ann.empty:
        lines.append(f"- Announcements: {len(ann):,}, {ann['announced_at'].min().date()} -> "
                     f"{ann['announced_at'].max().date()}")
    for name in ("announcements", "fundamentals", "statements", "prices_total_return"):
        p = store.path("seed", "akd", f"{name}.parquet")
        if p.exists():
            lines.append(f"- AKD seed {name}: {len(pd.read_parquet(p)):,} rows")
    return "\n".join(lines) + "\n"


def run() -> "Path":
    raw = store.read_parquet(store.path("prices", "daily_raw.parquet"))
    daily = store.read_parquet(store.path("prices", "daily.parquet"))
    events = store.read_parquet(store.path("prices", "corporate_actions.parquet"))
    if raw.empty or daily.empty:
        raise FileNotFoundError("run backfill-prices and adjust first")
    sections = [f"# Data-quality report — {date.today()}", "",
                "Source: PSX Data Portal (dps.psx.com.pk). Independent check: legacy AKD pulls.", ""]
    summary = {}
    for title, fn in (("1. Coverage", lambda: coverage(raw, daily)),
                      ("2. Daily returns vs AKD", lambda: vs_akd_returns(daily)),
                      ("3. Corporate actions vs AKD", lambda: vs_akd_events(events, daily)),
                      ("4. Suspicious moves", lambda: suspicious_moves(daily, events)),
                      ("5. Market proxy vs KSE-100", market_proxy_check)):
        log.info("quality: %s", title)
        text, res = fn()
        summary[title] = res
        sections += [f"## {title}", "", text, ""]
    sections += ["## 6. Other tables", "", other_tables(), "", "## 7. Known data limits", "",
                 KNOWN_LIMITS]
    out = config.REPORTS_DIR / "data_quality.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sections), encoding="utf-8")
    log.info("quality summary: %s", summary)
    return out
