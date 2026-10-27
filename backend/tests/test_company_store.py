from datetime import date
from pathlib import Path

import pandas as pd

from mbf import config, store
from mbf.ingest import company
from mbf.psx.client import PSXError

PAGE = (Path(__file__).parent / "fixtures" / "company_OGDC.html").read_text(encoding="utf-8")


class ReportsDown:
    """Company pages work; the separate report-list page is returning HTTP 500."""
    def __init__(self):
        self.report_calls = 0

    def company(self, s):
        return PAGE

    def company_reports(self, s):
        self.report_calls += 1
        raise PSXError(f"GET /company/reports/{s} -> HTTP 500")


def test_sweep_keeps_companies_and_stops_asking_when_report_list_is_down(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    c = ReportsDown()
    syms = [f"S{i:02d}" for i in range(10)]
    out = company.sweep(c, syms, with_reports=True, snapshot_date=date(2026, 10, 23))
    assert out["failed"] == []
    assert c.report_calls == company.REPORTS_GIVE_UP
    assert out["reports_failed"] == company.REPORTS_GIVE_UP
    assert out["reports_skipped"] == len(syms) - company.REPORTS_GIVE_UP
    snap = pd.read_parquet(store.path("fundamentals", "snapshots", "2026-10-23", "financials.parquet"))
    assert sorted(snap["symbol"].unique()) == syms


def test_partial_sweep_upserts_into_same_day_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    p = store.path("fundamentals", "snapshots", "2026-10-13", "quote.parquet")
    full = pd.DataFrame({"symbol": ["AAA", "BBB", "CCC"], "pe_ttm": [5.0, 6.0, 7.0]})
    company._upsert(full, p, {"AAA", "BBB", "CCC"})
    partial = pd.DataFrame({"symbol": ["BBB"], "pe_ttm": [9.0]})
    company._upsert(partial, p, {"BBB"})
    got = pd.read_parquet(p).set_index("symbol")["pe_ttm"].to_dict()
    assert got == {"AAA": 5.0, "BBB": 9.0, "CCC": 7.0}
