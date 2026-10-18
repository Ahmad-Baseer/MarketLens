from datetime import date

import numpy as np
import pandas as pd
import pytest

from mbf.signals import dividend, ledger, par
from mbf.signals.calendar import Calendar, dates_in_text
from mbf.signals.warnings import _outgoing


# ------------------------------------------------------------------ calendar
def test_holiday_dates_formats():
    t = ("shall remain closed from Tuesday, May 26th, 2026, till Thursday, May\n28th, 2026, on account "
         "of Eid. 3 Eid-ul-Fitr* 21st, 22nd & 23rd March 2026 Kashmir Day Thursday, 5th February, 2026 "
         "closed on Wednesday, August 26, 2026")
    d = dates_in_text(t)
    for x in [date(2026, 5, 26), date(2026, 5, 27), date(2026, 5, 28), date(2026, 3, 21),
              date(2026, 3, 22), date(2026, 3, 23), date(2026, 2, 5), date(2026, 8, 26)]:
        assert x in d


def test_resume_date_is_not_a_holiday():
    t = ("closed from Monday, March 31, 2025 till Wednesday, April 2, 2025 on account of Eid. "
         "The Exchange shall resume with Pre-Ramadan Trading Hours w.e.f. Thursday, April 3, 2025")
    d = dates_in_text(t)
    assert date(2025, 4, 2) in d and date(2025, 4, 3) not in d


def test_calendar_skips_weekends_and_holidays():
    past = pd.bdate_range("2026-10-05", "2026-10-09")            # Mon..Fri
    cal = Calendar(past, holiday_dates={pd.Timestamp("2026-10-13")}, horizon_days=20)
    assert cal.shift("2026-10-09", 1) == pd.Timestamp("2026-10-12")
    assert cal.shift("2026-10-12", 1) == pd.Timestamp("2026-10-14")  # 13th is a holiday
    assert cal.shift("2026-10-14", -1) == pd.Timestamp("2026-10-12")
    assert cal.between("2026-10-09", "2026-10-15") == 3              # 12, 14, 15


# ------------------------------------------------------------------ par / ex-date
def test_par_snap():
    assert par._snap(10.3) == 10 and par._snap(4.9) == 5 and np.isnan(par._snap(7.5))


def test_ex_date_t2_then_t1():
    s = pd.bdate_range("2025-12-01", "2026-03-31")
    # before the T+1 switch: book closure start minus two sessions
    assert par.ex_date_for(pd.Timestamp("2026-01-14"), s) == pd.Timestamp("2026-01-12")
    # from 2026-02-09: minus one session (a Monday book closure -> the Friday before)
    assert par.ex_date_for(pd.Timestamp("2026-03-02"), s) == pd.Timestamp("2026-02-27")
    assert par.ex_date_for(pd.Timestamp("2027-01-01"), s) is None


# ------------------------------------------------------------------ signal generation
def _cal():
    return Calendar(pd.bdate_range("2026-01-05", "2026-03-06"), holiday_dates=set(), horizon_days=60)


def _event(**kw):
    e = {"symbol": "ABC", "announced_at": pd.Timestamp("2026-02-02 15:30"), "div_rs": 4.0,
         "div_pct": 40.0, "par": 10.0, "has_bonus": False, "has_right": False,
         "bc_from": pd.Timestamp("2026-02-24"), "bc_to": pd.Timestamp("2026-02-28"),
         "ex_date": pd.Timestamp("2026-02-23"), "ex_basis": "book_closure", "source": "psx",
         "details": "40%(F) (D)"}
    e.update(kw)
    return pd.DataFrame([e])


def _feats(close=100.0, universe=True):
    return pd.DataFrame([{"symbol": "ABC", "close": close, "atr_pct": 0.02, "in_universe": universe,
                          "to_rank": 50.0, "med_to20": 5e7}])


def test_k5_published_the_evening_before_entry():
    cal = _cal()
    # ex-date Mon 23 Feb -> entry 5 sessions before = Mon 16 Feb -> published Fri 13 Feb
    s = dividend.generate(_event(), _feats(), pd.Timestamp("2026-02-13"), cal)
    k5 = [x for x in s if x["type"] == "DIV_K5"]
    assert len(k5) == 1
    k = k5[0]
    assert k["entry_date"] == pd.Timestamp("2026-02-16") and k["exit_date"] == pd.Timestamp("2026-02-23")
    assert k["nights"] == 5 and k["yield"] == pytest.approx(0.04)
    assert k["max_entry_price"] == pytest.approx(102.0) and k["stop_pct"] == pytest.approx(0.06)
    day_before = dividend.generate(_event(), _feats(), pd.Timestamp("2026-02-12"), cal)
    assert all(x["type"] != "DIV_K5" for x in day_before)


@pytest.mark.parametrize("close,universe,bonus,ok", [
    (100.0, True, False, True),       # 4% yield
    (250.0, True, False, False),      # 1.6%: below the band
    (50.0, True, False, False),       # 8%: above the band (special payouts priced early)
    (100.0, False, False, False),     # illiquid
    (100.0, True, True, False),       # bonus attached
])
def test_k5_filters(close, universe, bonus, ok):
    s = dividend.generate(_event(has_bonus=bonus), _feats(close, universe), pd.Timestamp("2026-02-13"), _cal())
    assert any(x["type"] == "DIV_K5" for x in s) == ok


def test_not_published_before_announcement():
    late = _event(announced_at=pd.Timestamp("2026-02-13 19:00"))     # after the evening run
    assert not dividend.generate(late, _feats(), pd.Timestamp("2026-02-13"), _cal())


def test_early_entry_on_announcement_evening():
    s = dividend.generate(_event(), _feats(), pd.Timestamp("2026-02-02"), _cal())
    assert [x["type"] for x in s] == ["DIV_3W"]
    assert s[0]["entry_date"] == pd.Timestamp("2026-02-03")


# ------------------------------------------------------------------ outcome tracking
def _daily(rows, start="2026-02-13"):
    d = pd.DataFrame(rows, columns=["open", "high", "low", "close", "traded"])
    d["date"] = pd.bdate_range(start, periods=len(d))
    d["symbol"] = "ABC"
    d["ldcp"] = d["close"].shift(1).fillna(d["close"])
    for c in ("open", "high", "low", "close"):
        d[f"adj_{c}"] = d[c]
    d["factor"] = 1.0
    return d


def _sig(**kw):
    s = {"id": "X", "symbol": "ABC", "entry_date": pd.Timestamp("2026-02-16"),
         "exit_date": pd.Timestamp("2026-02-23"), "ex_date": pd.Timestamp("2026-02-23"),
         "max_entry_price": 102.0, "stop_pct": 0.06, "div_rs": 4.0}
    s.update(kw)
    return pd.DataFrame([s])


FLAT = (100, 101, 99, 100, True)


def test_track_exit_at_ex_date_open_collects_dividend():
    rows = [FLAT, FLAT, FLAT, FLAT, FLAT, FLAT, (97, 98, 96, 97, True)]   # 13..23 Feb
    d = _daily(rows)
    # ex-date: PSX marks LDCP down by the dividend; adjusted series has no drop
    d.loc[d.index[-1], ["adj_open", "adj_high", "adj_low", "adj_close"]] = [101, 102, 100, 101]
    d.loc[d.index[-1], "factor"] = 0.96
    o = ledger.track(_sig(), d, cost=0.0, div_tax=0.0).iloc[0]
    assert o.status == "closed" and o.outcome == "exit_ex_date"
    assert o.exit_price == 97 and o.dividend == 4.0 and o.net == pytest.approx(0.01)


def test_track_stop():
    rows = [FLAT, FLAT, (99, 99, 93, 95, True), FLAT, FLAT, FLAT, FLAT]
    o = ledger.track(_sig(), _daily(rows), cost=0.0).iloc[0]
    assert o.outcome == "stop" and o.net == pytest.approx(-0.06)


def test_track_skips_a_chased_entry():
    rows = [FLAT, (100, 104, 100, 103, True), FLAT, FLAT, FLAT, FLAT, FLAT]
    o = ledger.track(_sig(), _daily(rows)).iloc[0]
    assert o.status == "skipped"


def test_track_pending_and_open():
    d = _daily([FLAT])                                               # only the signal day exists
    assert ledger.track(_sig(), d).iloc[0].status == "pending_entry"
    d = _daily([FLAT, FLAT, (100, 102, 99, 101, True)])
    o = ledger.track(_sig(), d, cost=0.0).iloc[0]
    assert o.status == "open" and o.net == pytest.approx(0.01)


# ------------------------------------------------------------------ KSE-30 notices
def test_kse30_row_parsing():
    syms = {"NRL", "APL", "TPLP", "TPL", "PIOC", "BAFL", "GHNI"}
    names = {"bank alfalah": "BAFL", "ghandhara industries": "GHNI"}
    assert _outgoing("NRL National Refinery Limited APL Attock Petroleum Limited", syms, False, names) == "APL"
    assert _outgoing("TPLP TPL Properties Limited PIOC Pioneer Cement Limited", syms, False, names) == "PIOC"
    assert _outgoing("Ghandhara Industries Limited Bank Alfalah Limited", syms, False, names) == "BAFL"
    assert _outgoing("Bank Alfalah Limited Ghandhara Industries Limited", syms, True, names) == "BAFL"


# ------------------------------------------------------------------ live record vs replay
def test_live_signal_supersedes_its_backtest_twin(tmp_path, monkeypatch):
    from mbf import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    base = {"type": "DIV_K5", "symbol": "ABC", "signal_date": pd.Timestamp("2026-10-14")}
    (tmp_path / "ledger").mkdir()
    pd.DataFrame([dict(base, id="A", mode="live")]).to_parquet(tmp_path / "ledger" / "signals.parquet")
    pd.DataFrame([dict(base, id="A", mode="backtest"), dict(base, id="B", mode="backtest")]).to_parquet(
        tmp_path / "ledger" / "backtest.parquet")
    s = ledger.load("all")
    assert sorted(s["id"]) == ["A", "B"]
    assert s.set_index("id").loc["A", "mode"] == "live"


@pytest.mark.parametrize("now,ok", [
    ("2026-10-19 08:00", True),     # catch-up on the morning of the buy day
    ("2026-10-19 14:59", True),
    ("2026-10-19 15:00", False),    # the last half hour has started
    ("2026-10-20 09:00", False),    # the buy day is over
])
def test_signal_only_published_while_actionable(now, ok):
    from mbf.signals.engine import publishable
    sig = {"id": "X", "symbol": "ABC", "entry_date": pd.Timestamp("2026-10-19")}
    good, late = publishable([sig], pd.Timestamp(now))
    assert (len(good) == 1) == ok and (len(late) == 1) != ok


# ------------------------------------------------------------------ fundamentals snapshots
def test_latest_fundamentals_take_each_company_from_its_newest_snapshot(tmp_path, monkeypatch):
    """A weekday evening refreshes only that day's reporters; the newest snapshot is partial."""
    from mbf import config, fundamentals
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    full = tmp_path / "fundamentals" / "snapshots" / "2026-10-18"
    part = tmp_path / "fundamentals" / "snapshots" / "2026-10-19"
    full.mkdir(parents=True)
    part.mkdir(parents=True)
    pd.DataFrame({"symbol": ["A", "B", "C"], "shares": [1, 2, 3]}).to_parquet(full / "equity.parquet")
    pd.DataFrame({"symbol": ["A"], "shares": [10]}).to_parquet(part / "equity.parquet")
    eq = fundamentals.latest("equity").set_index("symbol")
    assert sorted(eq.index) == ["A", "B", "C"]
    assert eq.loc["A", "shares"] == 10 and eq.loc["B", "shares"] == 2
    assert eq.loc["A", "snapshot"] == pd.Timestamp("2026-10-19")
