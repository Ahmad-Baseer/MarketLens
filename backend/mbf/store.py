"""On-disk layout. Plain Parquet files so the same data works locally, in CI
caches and on a server, and DuckDB/pandas can read it directly.

data/
  raw/historical/YYYY/YYYY-MM-DD.parquet   one file per trading day (as fetched)
  raw/historical/YYYY/YYYY-MM-DD.holiday   empty marker: PSX returned no rows
  prices/daily_raw.parquet                 all days compacted
  prices/daily.parquet                     + corporate-action adjustment
  prices/corporate_actions.parquet         one row per detected ex-date
  indices/eod.parquet
  ref/symbols.parquet, ref/market_watch.parquet
  fundamentals/snapshots/YYYY-MM-DD/*.parquet
  fundamentals/reports.parquet
  events/payouts.parquet, events/announcements.parquet
  seed/akd/*.parquet                       one-time import of the old AKD pulls
"""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

from mbf import config


def path(*parts: str) -> Path:
    p = config.DATA_DIR.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_parquet(df: pd.DataFrame, p: Path) -> Path:
    """Atomic write: a crash mid-write never leaves a truncated file behind."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    os.close(fd)
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return p


def read_parquet(p: Path, **kw) -> pd.DataFrame:
    return pd.read_parquet(p, **kw) if p.exists() else pd.DataFrame()


# ---------------------------------------------------------- daily price files
def day_file(d: date) -> Path:
    return config.DATA_DIR / "raw" / "historical" / str(d.year) / f"{d.isoformat()}.parquet"


def holiday_file(d: date) -> Path:
    return day_file(d).with_suffix(".holiday")


def day_done(d: date) -> bool:
    return day_file(d).exists() or holiday_file(d).exists()


def mark_holiday(d: date):
    p = holiday_file(d)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    if day_file(d).exists():
        day_file(d).unlink()


def fetched_days() -> tuple[list[date], list[date]]:
    """(trading days, holidays) already on disk."""
    root = config.DATA_DIR / "raw" / "historical"
    if not root.exists():
        return [], []
    trading = sorted(date.fromisoformat(p.stem) for p in root.glob("*/*.parquet"))
    holidays = sorted(date.fromisoformat(p.stem) for p in root.glob("*/*.holiday"))
    return trading, holidays
