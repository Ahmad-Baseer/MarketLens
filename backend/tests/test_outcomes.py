import numpy as np
import pandas as pd
import pytest

from mbf.research.outcomes import ExitRule, simulate

RULE = ExitRule("t", horizon=3, stop_atr=1.0, target_atr=2.0, max_chase=0.5)
# with close 100 and ATR 5%: stop = 95, target = 110, chase cap = 105


def path(bars, atr=0.05, locked_up=None, locked_dn=None, factor=None):
    """bars: list of (open, high, low, close, traded). Row 0 is the signal day."""
    n = len(bars)
    return pd.DataFrame({
        "symbol": "X", "date": pd.bdate_range("2026-01-05", periods=n),
        "adj_open": [b[0] for b in bars], "adj_high": [b[1] for b in bars],
        "adj_low": [b[2] for b in bars], "adj_close": [b[3] for b in bars],
        "traded": [b[4] for b in bars], "atr_pct": atr,
        "locked_up": locked_up or [False] * n, "locked_dn": locked_dn or [False] * n,
        "factor": factor or [1.0] * n})


def first(bars, **kw):
    return simulate(path(bars, **kw), RULE, cost=0.0).iloc[0]


def test_target_hit():
    r = first([(100, 100, 100, 100, 1), (101, 104, 100, 103, 1), (103, 111, 102, 109, 1),
               (109, 109, 108, 108, 1)])
    assert r.outcome == "target" and r.days == 2 and r.gross == pytest.approx(110 / 101 - 1)


def test_stop_hit():
    r = first([(100, 100, 100, 100, 1), (101, 102, 94, 96, 1), (96, 97, 95, 96, 1),
               (96, 96, 96, 96, 1)])
    assert r.outcome == "stop" and r.days == 1 and r.gross == pytest.approx(95 / 101 - 1)


def test_both_touched_same_day_counts_as_stop():
    r = first([(100, 100, 100, 100, 1), (101, 112, 94, 105, 1), (105, 106, 104, 105, 1),
               (105, 105, 105, 105, 1)])
    assert r.outcome == "stop"


def test_gap_down_through_stop_exits_at_open():
    r = first([(100, 100, 100, 100, 1), (101, 102, 100, 101, 1), (90, 92, 89, 91, 1),
               (91, 91, 91, 91, 1)])
    assert r.outcome == "gap_stop" and r.gross == pytest.approx(90 / 101 - 1)


def test_no_chasing_a_gap_up():
    r = first([(100, 100, 100, 100, 1), (106, 107, 105, 106, 1), (106, 106, 106, 106, 1),
               (106, 106, 106, 106, 1)])
    assert not r.entered and r.outcome == "skip"


def test_cannot_buy_upper_locked_open():
    r = first([(100, 100, 100, 100, 1), (104, 104, 104, 104, 1), (104, 104, 104, 104, 1),
               (104, 104, 104, 104, 1)], locked_up=[False, True, False, False])
    assert not r.entered


def test_stop_on_locked_down_day_exits_next_open():
    r = first([(100, 100, 100, 100, 1), (101, 101, 101, 101, 1), (91, 91, 91, 91, 1),
               (88, 90, 87, 89, 1), (89, 89, 89, 89, 1)],
              locked_dn=[False, False, True, False, False])
    # day 2 gaps below the stop at 91 -> gap_stop at the open (locked days still print an open)
    assert r.outcome in ("gap_stop", "locked_stop")


def test_locked_stop_when_range_touches_stop_on_locked_day():
    r = first([(100, 100, 100, 100, 1), (101, 101, 101, 101, 1), (96, 96, 94, 94, 1),
               (90, 92, 89, 91, 1), (91, 91, 91, 91, 1)],
              locked_dn=[False, False, True, False, False])
    assert r.outcome == "locked_stop" and r.gross == pytest.approx(90 / 101 - 1)


def test_time_exit_and_untraded_days():
    r = first([(100, 100, 100, 100, 1), (101, 103, 100, 102, 1), (102, 102, 102, 102, 0),
               (102, 104, 101, 103, 1)])
    assert r.outcome == "time" and r.days == 3 and r.gross == pytest.approx(103 / 101 - 1)


def test_not_entered_when_path_incomplete():
    r = first([(100, 100, 100, 100, 1), (101, 102, 100, 101, 1)])
    assert not r.entered


CLOSE_OPEN = ExitRule("co", horizon=2, entry="close", exit="open")


def test_close_entry_open_exit():
    # signal day 0; buy at day-1 close (102); hold 2 nights; sell at day-3 open (105)
    f = path([(100, 100, 100, 100, 1), (101, 103, 100, 102, 1), (103, 104, 102, 103, 1),
              (105, 106, 104, 104, 1), (104, 104, 104, 104, 1)])
    r = simulate(f, CLOSE_OPEN, cost=0.0).iloc[0]
    assert r.entered and r.outcome == "time" and r.days == 2
    assert r.gross == pytest.approx(105 / 102 - 1)


def test_close_entry_skips_if_already_ran():
    # day-1 close is 2 ATRs above the signal close: don't chase
    f = path([(100, 100, 100, 100, 1), (101, 111, 100, 110, 1), (110, 111, 109, 110, 1),
              (110, 110, 110, 110, 1), (110, 110, 110, 110, 1)])
    assert not simulate(f, CLOSE_OPEN, cost=0.0).iloc[0].entered


def test_close_entry_levels_from_entry_price():
    rule = ExitRule("cs", horizon=3, stop_atr=1.0, target_atr=2.0, entry="close", exit="open")
    # entry 102 at day-1 close -> stop 96.9, target 112.2; day 2 trades down to 96
    f = path([(100, 100, 100, 100, 1), (101, 103, 100, 102, 1), (101, 101, 96, 97, 1),
              (97, 98, 96, 97, 1), (97, 97, 97, 97, 1), (97, 97, 97, 97, 1)])
    r = simulate(f, rule, cost=0.0).iloc[0]
    assert r.outcome == "stop" and r.gross == pytest.approx(102 * 0.95 / 102 - 1)


def test_dividend_collected_when_held_into_ex_date_is_taxed():
    # adjusted prices flat at 100; day 2 is an ex-date for a 2% cash dividend (factor 0.98)
    bars = [(100, 100, 100, 100, 1)] * 5
    f = path(bars, factor=[1, 1, 0.98, 1, 1])
    r = simulate(f, CLOSE_OPEN, cost=0.0).iloc[0]       # buy day-1 close, sell day-3 open
    assert r.gross == pytest.approx(-0.15 * 0.02)          # flat total return minus 15% of the 2%
    rule_before = ExitRule("cb", horizon=1, entry="close", exit="open")
    r2 = simulate(path(bars, factor=[1, 1, 1, 0.98, 1]), rule_before, cost=0.0).iloc[0]
    assert r2.gross == pytest.approx(0.0)                  # sold before the ex-date: no dividend, no tax


def test_cost_is_deducted():
    f = path([(100, 100, 100, 100, 1), (101, 103, 100, 102, 1), (102, 103, 101, 102, 1),
              (102, 104, 101, 103, 1)])
    r = simulate(f, RULE, cost=0.006).iloc[0]
    assert r.net == pytest.approx(r.gross - 0.006)
