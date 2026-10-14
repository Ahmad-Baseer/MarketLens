"""Trading calendar: past sessions from PSX's own data, future sessions predicted
from weekdays minus the holidays PSX has announced.

PSX publishes an annual holiday calendar (moon-dependent dates are provisional)
and a specific notice a few days before each holiday. A specific notice wins over
the annual calendar for dates near it (e.g. 2026: calendar said Eid-ul-Azha
27-29 May, the notice said 26-28 May).
"""
from __future__ import annotations

import io
import logging
import re
from datetime import date

import pandas as pd

from mbf import store
from mbf.psx.client import PSXClient

log = logging.getLogger(__name__)

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], 1)}
_M = "(" + "|".join(MONTHS) + ")"
_D = r"(\d{1,2})(?:st|nd|rd|th)?"
HOLIDAY_TITLE = re.compile(r"HOLIDAY|REMAIN CLOSED", re.I)
NOT_HOLIDAY = re.compile(r"NCCPL|Settlement|Clearing|SUKUK", re.I)


def _mk(y, m, d) -> date | None:
    try:
        return date(int(y), MONTHS[m.lower()], int(d))
    except (ValueError, KeyError):
        return None


def dates_in_text(text: str) -> list[date]:
    """Every calendar date written in a PSX holiday notice, with ranges expanded."""
    t = re.sub(r"\s+", " ", text)
    # "... trading will resume on Wednesday, April 15" names a session, not a holiday
    t = re.sub(r"(?:resum|re-?open|will open|normal trading).*?\d{4}", " ", t, flags=re.I)
    out: list[date] = []
    # "from Tuesday, May 26th, 2026, till Thursday, May 28th, 2026"
    for m in re.finditer(rf"from (?:\w+, )?{_M} {_D},? (\d{{4}}),? (?:till|to|until) (?:\w+, )?{_M} {_D},? (\d{{4}})", t, re.I):
        a, b = _mk(m.group(3), m.group(1), m.group(2)), _mk(m.group(6), m.group(4), m.group(5))
        if a and b and 0 <= (b - a).days <= 10:
            out += [d.date() for d in pd.date_range(a, b)]
    # "21st, 22nd & 23rd March 2026" / "24th & 25th June, 2026"
    for m in re.finditer(rf"((?:\d{{1,2}}(?:st|nd|rd|th)?\s*(?:,|&|and)\s*)+\d{{1,2}}(?:st|nd|rd|th)?) {_M},? (\d{{4}})", t, re.I):
        for d in re.findall(r"\d{1,2}", m.group(1)):
            x = _mk(m.group(3), m.group(2), d)
            if x:
                out.append(x)
    # "5th February, 2026"
    for m in re.finditer(rf"{_D} {_M},? (\d{{4}})", t, re.I):
        x = _mk(m.group(3), m.group(2), m.group(1))
        if x:
            out.append(x)
    # "August 26, 2026" / "May 26th, 2026"
    for m in re.finditer(rf"{_M} {_D},? (\d{{4}})", t, re.I):
        x = _mk(m.group(3), m.group(1), m.group(2))
        if x:
            out.append(x)
    return sorted(set(out))


def update_holidays(client: PSXClient, since: str = "2024-01-01") -> pd.DataFrame:
    """Read every PSX holiday notice since `since` (text PDFs; small) into
    data/ref/holidays.parquet: date, source ('calendar' | 'notice'), notice date."""
    import pdfplumber

    p = store.path("ref", "holidays.parquet")
    old = store.read_parquet(p)
    done = set(old["doc_id"]) if not old.empty else set()
    n = store.read_parquet(store.path("events", "psx_notices.parquet"))
    n = n[n["title"].str.contains(HOLIDAY_TITLE) & ~n["title"].str.contains(NOT_HOLIDAY)
          & (n["announced_at"] >= since) & n["pdf_url"].str.endswith(".pdf", na=False)]
    rows = []
    for r in n.itertuples():
        if r.doc_id in done:
            continue
        try:
            b = client.download(r.pdf_url)
            with pdfplumber.open(io.BytesIO(b)) as pdf:
                text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
        except Exception as e:                      # one bad PDF must not stop the run
            log.warning("holiday notice %s: %s", r.pdf_url, e)
            continue
        kind = "calendar" if re.search(r"HOLIDAY CALENDAR", r.title, re.I) else "notice"
        for d in dates_in_text(text):
            if d != r.announced_at.date() and d >= r.announced_at.date() and d.weekday() < 5:
                rows.append({"date": pd.Timestamp(d), "source": kind,
                             "announced_at": r.announced_at, "doc_id": r.doc_id, "title": r.title})
    new = pd.DataFrame(rows)
    allh = pd.concat([old, new], ignore_index=True) if not old.empty else new
    if not allh.empty:
        allh = allh.drop_duplicates(["date", "doc_id"]).sort_values("date").reset_index(drop=True)
        store.write_parquet(allh, p)
    log.info("holidays: %d dates from %d notices", len(allh), allh["doc_id"].nunique() if len(allh) else 0)
    return allh


def holidays() -> set[pd.Timestamp]:
    h = store.read_parquet(store.path("ref", "holidays.parquet"))
    if h.empty:
        return set()
    notice = h[h["source"] == "notice"]
    cal = h[h["source"] == "calendar"]
    keep = set(notice["date"])
    for r in cal.itertuples():
        # a later specific notice within 4 days replaces the provisional calendar date
        near = notice[(notice["announced_at"] > r.announced_at)
                      & ((notice["date"] - r.date).abs() <= pd.Timedelta(days=4))]
        if near.empty:
            keep.add(r.date)
    return keep


class Calendar:
    """sessions = PSX sessions we have data for, then predicted weekdays."""

    def __init__(self, sessions: pd.DatetimeIndex, holiday_dates: set | None = None,
                 horizon_days: int = 120):
        self.past = pd.DatetimeIndex(sorted(sessions))
        hol = holiday_dates if holiday_dates is not None else holidays()
        start = self.past[-1] + pd.Timedelta(days=1)
        fut = pd.bdate_range(start, start + pd.Timedelta(days=horizon_days))
        self.future = pd.DatetimeIndex([d for d in fut if d not in hol])
        self.all = self.past.append(self.future)

    @property
    def last(self) -> pd.Timestamp:
        return self.past[-1]

    def index(self, d) -> int:
        """Position of the first session on/after d."""
        return int(self.all.searchsorted(pd.Timestamp(d)))

    def shift(self, d, n: int) -> pd.Timestamp:
        """The session n sessions after (n<0: before) the first session on/after d."""
        return self.all[self.index(d) + n]

    def prev_session(self, d) -> pd.Timestamp:
        """Last session strictly before d."""
        return self.all[self.all.searchsorted(pd.Timestamp(d)) - 1]

    def between(self, a, b) -> int:
        """Sessions after a up to and including b."""
        return self.index(pd.Timestamp(b) + pd.Timedelta(days=1)) - self.index(pd.Timestamp(a) + pd.Timedelta(days=1))
