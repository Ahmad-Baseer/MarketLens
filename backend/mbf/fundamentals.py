"""The latest known figures for every company.

Snapshots are written per sweep date, and a weekday evening refreshes only the companies
that just reported results (often fewer than 15). So the newest snapshot on its own is
incomplete: anything that needs "current fundamentals" must take each company's rows from
the most recent snapshot that contains that company.
"""
from __future__ import annotations

import pandas as pd

from mbf import store


def snapshot_dirs() -> list:
    return sorted(store.path("fundamentals", "snapshots").glob("*"))


def latest(table: str) -> pd.DataFrame:
    """table: info | quote | equity | financials | ratios. One company's rows all come from
    the same (its newest) snapshot, with that date in the `snapshot` column."""
    frames = []
    for sd in snapshot_dirs():
        f = sd / f"{table}.parquet"
        if f.exists():
            df = pd.read_parquet(f)
            if not df.empty:
                df["snapshot"] = pd.Timestamp(sd.name)
                frames.append(df)
    if not frames:
        return pd.DataFrame()
    allr = pd.concat(frames, ignore_index=True)
    newest = allr.groupby("symbol")["snapshot"].transform("max")
    return allr[allr["snapshot"] == newest].reset_index(drop=True)
