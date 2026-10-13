import numpy as np
import pandas as pd
import pytest

from mbf.adjust import adjust


def rows(symbol, data, row_type="equity"):
    # data: (date, ldcp, open, high, low, close, volume)
    return [dict(date=pd.Timestamp(d), symbol=symbol, row_type=row_type, ldcp=l, open=o,
                 high=h, low=lo, close=c, volume=v) for d, l, o, h, lo, c, v in data]


@pytest.fixture
def raw():
    a = rows("AAA", [
        ("2026-01-01", 99.0, 99, 101, 98, 100.0, 1000),
        ("2026-01-02", 100.0, 100, 103, 99, 102.0, 1000),
        ("2026-01-05", 100.0, 100, 102, 99, 101.0, 1000),   # ex Rs 2 dividend: 102 - 2
        ("2026-01-06", 80.8, 81, 82, 80, 81.0, 1000),       # ex 25% bonus: 101 / 1.25
        ("2026-01-07", 81.0, 0, 0, 0, 81.0, 0),             # untraded
    ])
    b = rows("BBB", [
        ("2026-01-01", 10.0, 10, 10, 10, 10.0, 5),
        ("2026-01-02", 0.001, 10, 11, 10, 10.5, 5),          # garbage LDCP
    ])
    c = rows("CCC", [
        ("2025-06-02", 20.0, 20, 20, 20, 20.0, 10),
        ("2026-01-02", 30.0, 30, 31, 29, 30.5, 10),          # back after 7 months away
    ])
    fut = rows("AAA-JAN", [("2026-01-02", 50.0, 50, 50, 50, 55.0, 1)])
    debt = rows("P01GHS1", [("2026-01-02", 99.0, 99, 99, 99, 98.0, 1)], row_type="debt")
    # bonds and index codes that PSX's daily table labels 'equity'
    mislabelled = (rows("P01GIS031225", [("2026-01-02", 99.6, 99, 100, 99, 99.6, 1e10)])
                   + rows("PK03TB011026", [("2026-01-02", 98.0, 98, 98, 98, 98.0, 1e6)])
                   + rows("ABLTFC2", [("2026-01-02", 100.0, 100, 100, 100, 100.0, 10)])
                   + rows("KSE100", [("2026-01-02", 165000.0, 1, 1, 1, 165100.0, 1e8)]))
    return pd.DataFrame(a + b + c + fut + debt + mislabelled)


def test_excludes_futures_debt_and_indices(raw):
    daily, _ = adjust(raw, exclude={"KSE100"})
    assert set(daily["symbol"]) == {"AAA", "BBB", "CCC"}


def test_long_absence_is_not_a_corporate_action(raw):
    daily, ev = adjust(raw)
    c = daily[daily.symbol == "CCC"].set_index("date")
    assert c.loc["2026-01-02", "factor"] == 1.0
    assert c.loc["2026-01-02", "ret"] == pytest.approx(30.5 / 30 - 1)   # PSX's own day change
    e = ev[ev.symbol == "CCC"].iloc[0]
    assert not e.applied and e.kind_guess == "after_gap"


def test_factors_and_events(raw):
    daily, ev = adjust(raw)
    a = daily[daily.symbol == "AAA"].set_index("date")
    assert a.loc["2026-01-05", "factor"] == pytest.approx(100 / 102)
    assert a.loc["2026-01-06", "factor"] == pytest.approx(0.8)
    assert a.loc["2026-01-02", "factor"] == 1.0
    e = ev[ev.symbol == "AAA"]
    assert len(e) == 2 and e["applied"].all()
    assert e.iloc[0]["implied_cash"] == pytest.approx(2.0)


def test_back_adjusted_series_matches_returns(raw):
    daily, _ = adjust(raw)
    a = daily[daily.symbol == "AAA"].set_index("date")
    # latest bar is unadjusted; earliest carries both events
    assert a.loc["2026-01-07", "adj_close"] == 81.0
    assert a.loc["2026-01-01", "adj_close"] == pytest.approx(100 * (100 / 102) * 0.8)
    # total return from LDCP equals the change in the adjusted series
    chained = (1 + a["ret"].iloc[1:]).prod()
    assert chained == pytest.approx(a["adj_close"].iloc[-1] / a["adj_close"].iloc[0])
    assert a.loc["2026-01-05", "ret"] == pytest.approx(0.01)


def test_untraded_day_flattened(raw):
    daily, _ = adjust(raw)
    r = daily[(daily.symbol == "AAA") & (daily.date == "2026-01-07")].iloc[0]
    assert not r.traded
    assert r.open == r.high == r.low == r.close == 81.0


def test_zero_close_rows_dropped_and_no_infinite_returns():
    raw = pd.DataFrame(rows("ZZZ", [
        ("2026-01-01", 0.0, 0, 0, 0, 0.0, 0),               # listed with no price at all
        ("2026-01-02", 0.0, 6, 6, 5.5, 5.8, 100),           # first trade, no LDCP
        ("2026-01-05", 5.8, 5.8, 6.0, 5.7, 5.9, 100),
    ]))
    daily, _ = adjust(raw)
    z = daily.set_index("date")
    assert pd.Timestamp("2026-01-01") not in z.index
    assert np.isnan(z.loc["2026-01-02", "ret"])
    assert z.loc["2026-01-05", "ret"] == pytest.approx(5.9 / 5.8 - 1)
    assert np.isfinite(daily["ret"].dropna()).all()


def test_pre_modern_rows_have_no_open_and_no_ldcp_adjustment():
    raw = pd.DataFrame(rows("OLD", [("2012-05-02", 10.0, 10.0, 11, 9.8, 10.5, 100),
                                    ("2012-05-03", 9.0, 9.0, 10, 8.9, 9.5, 100),   # noisy LDCP
                                    ("2013-11-04", 9.5, 9.7, 10, 9.4, 9.9, 100)]))
    daily, ev = adjust(raw)
    o = daily.set_index("date")
    assert np.isnan(o.loc["2012-05-02", "open"]) and np.isnan(o.loc["2012-05-02", "adj_open"])
    assert o.loc["2012-05-02", "low"] == 9.8          # fake open no longer distorts the range
    assert o.loc["2013-11-04", "open"] == 9.7
    assert ev.empty                                  # the 2012 LDCP gap is not an event
    assert o.loc["2012-05-03", "ret"] == pytest.approx(9.5 / 10.5 - 1)
    assert not o.loc["2012-05-03", "modern"] and o.loc["2013-11-04", "modern"]


def test_index_codes_excluded_case_insensitively():
    raw = pd.DataFrame(rows("BKTi", [("2017-05-03", 0.0, 1, 1, 1, 20302.4, 1e7)])
                       + rows("AAA", [("2017-05-03", 10.0, 10, 10, 10, 10.0, 1)]))
    daily, _ = adjust(raw, exclude={"BKTI"})
    assert set(daily["symbol"]) == {"AAA"}


def test_suspect_flag(raw):
    daily, _ = adjust(raw)
    assert not daily["suspect"].any()           # nothing in the fixture breaks a circuit
    big = pd.DataFrame(rows("JMP", [("2026-01-01", 10.0, 10, 10, 10, 10.0, 1),
                                    ("2026-01-02", 10.0, 10, 50, 10, 50.0, 1)]))
    d2, _ = adjust(big)
    assert d2.set_index("date").loc["2026-01-02", "suspect"]


def test_implausible_factor_not_applied(raw):
    daily, ev = adjust(raw)
    b = daily[daily.symbol == "BBB"].set_index("date")
    assert b.loc["2026-01-02", "factor"] == 1.0
    assert b.loc["2026-01-02", "ret"] == pytest.approx(0.05)     # falls back to close/close
    assert not ev[ev.symbol == "BBB"]["applied"].iloc[0]
