import pandas as pd

from mbf import config, store
from mbf.ingest import company


def test_partial_sweep_upserts_into_same_day_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    p = store.path("fundamentals", "snapshots", "2026-10-13", "quote.parquet")
    full = pd.DataFrame({"symbol": ["AAA", "BBB", "CCC"], "pe_ttm": [5.0, 6.0, 7.0]})
    company._upsert(full, p, {"AAA", "BBB", "CCC"})
    partial = pd.DataFrame({"symbol": ["BBB"], "pe_ttm": [9.0]})
    company._upsert(partial, p, {"BBB"})
    got = pd.read_parquet(p).set_index("symbol")["pe_ttm"].to_dict()
    assert got == {"AAA": 5.0, "BBB": 9.0, "CCC": 7.0}
