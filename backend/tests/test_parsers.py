from datetime import date
from pathlib import Path

import math
import pandas as pd
import pytest

from mbf.psx import parsers as P

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_to_num():
    assert P.to_num("1,234.50") == 1234.5
    assert P.to_num("(18.71)") == -18.71
    assert P.to_num("15.00%") == 15.0
    assert math.isnan(P.to_num(""))
    assert math.isnan(P.to_num("N/A"))


def test_historical_day():
    df = P.parse_historical(read("historical_2026-10-12.html"), date(2026, 10, 12))
    assert len(df) == 7
    og = df.set_index("symbol").loc["OGDC"]
    assert (og.ldcp, og.open, og.high, og.low, og.close, og.volume) == \
        (306.12, 306.0, 307.99, 299.52, 300.39, 1929730.0)
    assert df.set_index("symbol").loc["P01GHS020927", "row_type"] == "debt"
    assert df.set_index("symbol").loc["MCB-OCTB", "row_type"] == "equity"   # futures look like equity
    assert df["date"].iloc[0] == pd.Timestamp("2026-10-12")


def test_historical_ex_date_ldcp_is_adjusted():
    """OGDC went ex Rs 6 dividend on 2026-10-08: LDCP 309.91 vs prior close 315.91."""
    df = P.parse_historical(read("historical_2026-10-08.html"), date(2026, 10, 8))
    assert df.set_index("symbol").loc["OGDC", "ldcp"] == 309.91


def test_historical_holiday_is_empty():
    assert P.parse_historical(read("historical_holiday.html"), date(2026, 8, 14)).empty


def test_market_watch():
    df = P.parse_market_watch(read("market_watch.html")).set_index("symbol")
    assert "KSE100" in df.loc["OGDC", "listed_in"].split(",")
    assert df.loc["LSEFSLR", "volume"] == 30082536
    assert df.loc["LSEFSLR", "change_pct"] == pytest.approx(-10.084)
    assert "Right" in df.loc["LSEFSLR", "name"]


def test_company_page():
    c = P.parse_company(read("company_OGDC.html"), "OGDC")
    info, q, eq = c["info"], c["quote"], c["equity"]
    assert info["name"] == "Oil & Gas Development Company Limited"
    assert info["tags"] == "XD"
    assert info["sector"] == "OIL & GAS EXPLORATION COMPANIES"
    assert info.get("fiscal_year_end")
    assert q["pe_ttm"] == 5.33
    assert (q["cb_low"], q["cb_high"]) == (270.35, 330.43)
    assert (q["wk52_low"], q["wk52_high"]) == (238.20, 352.00)
    assert q["ldcp"] == 300.39
    assert eq["shares"] == 4_300_928_400
    assert eq["free_float_pct"] == 15.0
    assert eq["free_float_shares"] == 645_139_260
    assert eq["market_cap_000"] == pytest.approx(1_291_267_733.53)

    f = c["financials"]
    assert set(f["kind"]) == {"annual", "quarterly"}
    assert len(f) == 2 * 3 * 4          # 2 tables x 3 items x 4 periods, no duplicates
    eps = f[(f.kind == "annual") & (f.item == "EPS")].set_index("period")["value"]
    assert eps["2026"] == 56.35 and eps["2023"] == 52.23
    q3 = f[(f.kind == "quarterly") & (f.period == "Q3 2026") & (f.item == "EPS")]
    assert q3["value"].iloc[0] == 9.82
    assert f[(f.kind == "annual") & (f.item == "Sales") & (f.period == "2025")]["value"].iloc[0] == 401_177_969

    r = c["ratios"].set_index(["period", "item"])["value"]
    assert r[("2025", "EPS Growth (%)")] == -18.71
    assert r[("2026", "Gross Profit Margin (%)")] == 54.94


@pytest.mark.parametrize("s,expected", [
    ("60% (F) (D)", [("dividend", 60, None, "F")]),
    ("30%(i) (D) - 50% (B)", [("dividend", 30, None, "I"), ("bonus", 50, None, None)]),
    ("50%)F) (D)", [("dividend", 50, None, "F")]),
    ("12.5%(ii (D)", [("dividend", 12.5, None, None)]),
    ("Rs. 8.25 (D)", [("dividend", None, 8.25, None)]),
    ("DIVIDEND =350% (F)", [("dividend", 350, None, "F")]),
    ("15% (B)", [("bonus", 15, None, None)]),
    ("40% (R)", [("right", 40, None, None)]),
])
def test_payout_details(s, expected):
    got = P.parse_payout_details(s)
    assert len(got) == len(expected)
    for g, (kind, pct, rs, tag) in zip(got, expected):
        assert g["kind"] == kind
        assert (math.isnan(g["pct"]) if pct is None else g["pct"] == pct)
        assert (math.isnan(g["rs"]) if rs is None else g["rs"] == rs)
        assert g["tag"] == tag


def test_payout_rights_premium_and_discount():
    prem = P.parse_payout_details("= 12.1433 AT A PREMIUM RS. 170 PER SHARE (R)")[0]
    assert prem["kind"] == "right" and prem["pct"] == 12.1433 and prem["issue_adj_rs"] == 170
    disc = P.parse_payout_details("100% AT A DISCOUNT OF Rs.1/= PER SHARE (R)")[0]
    assert disc["pct"] == 100 and disc["issue_adj_rs"] == -1


def test_payouts_table():
    df = P.parse_payouts(read("payouts.html"))
    s = df[df.symbol == "SSOM"].iloc[0]
    assert s.kind == "dividend" and s.pct == 50 and s.tag == "F"
    assert s.announced_at == pd.Timestamp("2026-10-06 15:50")
    assert s.book_closure_from == pd.Timestamp("2026-10-22")
    assert s.book_closure_to == pd.Timestamp("2026-10-28")


def test_announcements():
    df = P.parse_announcements(read("announcements.html"))
    assert len(df) == 50
    r = df.iloc[0]
    assert (r.symbol, r.title) == ("GOC", "General Meetings / Briefing Sessions")
    assert r.announced_at == pd.Timestamp("2026-10-12 15:27")
    assert r.doc_id == "285529"


def test_company_reports():
    df = P.parse_company_reports(read("reports_OGDC.html"), "OGDC")
    assert len(df) > 40
    first = df.iloc[0]
    assert (first.report_type, first.period, first.report_id) == ("Annual", "2013", "OGDC-ANNUAL-2012")
    assert first.url.startswith("https://financials.psx.com.pk/")


def test_eod_dates_are_karachi_trading_days():
    df = P.eod_to_frame([[1791802800, 300.39, 1929730, 306]], "OGDC")
    assert df["date"].iloc[0] == pd.Timestamp("2026-10-12")
