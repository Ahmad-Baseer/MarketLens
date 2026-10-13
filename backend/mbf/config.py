"""Paths and constants. Everything overridable by environment variable so the
same code runs on a laptop, in GitHub Actions and on a server."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]               # repo root (MBF/)
DATA_DIR = Path(os.environ.get("MBF_DATA_DIR", ROOT / "data"))
REPORTS_DIR = Path(os.environ.get("MBF_REPORTS_DIR", ROOT / "reports"))
LEGACY_AKD_DIR = Path(os.environ.get("MBF_AKD_DIR", ROOT / "legacy" / "akd_data"))
LEGACY_WORK_DIR = ROOT / "legacy" / "work"

PSX_BASE = "https://dps.psx.com.pk"
PSX_REPORTS_BASE = "https://financials.psx.com.pk"
# Identify honestly; PSX accepts a non-browser agent (verified 2026-10-13).
USER_AGENT = os.environ.get("MBF_USER_AGENT", "MBF-Signals/0.1 (personal research)")
# Minimum seconds between requests to PSX. One backfill is ~6,900 requests,
# so this keeps it polite (~1 req/s) without taking all day.
REQUEST_INTERVAL = float(os.environ.get("MBF_REQUEST_INTERVAL", "0.8"))

HISTORY_START = date(2000, 1, 1)     # /historical has nothing before 2000
# PSX's data changes character on 2013-11-04 (measured 2026-10-13). Before it:
#   * "open" is a copy of the previous close on ~90% of rows (no real opens);
#   * LDCP is blank on many rows and is NEVER adjusted for dividends/bonuses
#     (zero adjustments 2012Q1-2013Q3, then 35 in 2013Q4, ~80/quarter after).
# So adjusted prices, total returns and next-open entries are only reliable
# from this date. Older rows are kept, marked modern=False, for market context.
MODERN_FROM = date(2013, 11, 4)
# Ex-date = book-closure start minus the settlement lag, in sessions: T+2 until
# PSX moved to T+1 in the week of 2026-02-09 (measured from 2,900 payouts: 90-97%
# of ex-dates follow this rule exactly). Used to schedule dividend signals live.
T1_SETTLEMENT_FROM = date(2026, 2, 9)
# Aug-Dec 2008 the exchange held a price floor; almost nothing traded and
# positions could not be exited. Backtests must treat it as untradeable.
MARKET_FREEZE = (date(2008, 8, 27), date(2008, 12, 15))
TZ = "Asia/Karachi"

# Indices with an EOD series on PSX (only ~5 years deep).
INDICES = ["KSE100", "KSE30", "KMI30", "ALLSHR", "KMIALLSHR", "PSXDIV20"]
