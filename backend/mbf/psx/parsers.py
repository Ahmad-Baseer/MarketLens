"""Parse PSX Data Portal HTML fragments into tidy pandas frames.

Every parser is pure (HTML in, data out) so it can be tested against saved
fixtures. Numbers are read from ``data-value`` / ``data-order`` attributes where
PSX provides them — those are unformatted and exact.
"""
from __future__ import annotations

import re
from datetime import date, datetime

import numpy as np
import pandas as pd
from lxml import html as lh

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _doc(text: str):
    return lh.fromstring(text or "<div></div>")


def _txt(el) -> str:
    return re.sub(r"\s+", " ", el.text_content()).strip() if el is not None else ""


def to_num(s) -> float:
    """'1,234.5' -> 1234.5 ; '(18.71)' -> -18.71 ; '15.00%' -> 15.0 ; '' -> nan"""
    if s is None:
        return np.nan
    s = str(s).strip()
    if not s or s in {"-", "--", "N/A", "n/a"}:
        return np.nan
    neg = s.startswith("(") and s.endswith(")")
    m = _NUM_RE.search(s.replace("−", "-"))
    if not m:
        return np.nan
    try:
        v = float(m.group(0).replace(",", ""))
    except ValueError:
        return np.nan
    return -abs(v) if neg else v


def _range(s: str) -> tuple[float, float]:
    nums = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", s or "")]
    return (nums[0], nums[1]) if len(nums) >= 2 else (np.nan, np.nan)


# ----------------------------------------------------------------- historical
HIST_COLS = ["date", "symbol", "row_type", "ldcp", "open", "high", "low", "close", "volume"]


def parse_historical(text: str, d: date) -> pd.DataFrame:
    """POST /historical — one row per listed symbol for the day.

    Untraded symbols are listed with open/high/low = 0, volume = 0 and
    close = LDCP. Futures contracts appear as row_type 'equity' with a '-'
    suffix (e.g. 'MCB-OCTB'); they are kept here and filtered downstream.
    """
    rows = []
    for tr in _doc(text).xpath("//tbody/tr"):
        tds = tr.xpath("./td")
        if len(tds) != 9:
            continue
        v = [td.get("data-value") for td in tds]
        rows.append((d, (v[0] or _txt(tds[0])).strip(), tr.get("data-type") or "",
                     to_num(v[1]), to_num(v[2]), to_num(v[3]), to_num(v[4]), to_num(v[5]),
                     to_num(v[8])))
    df = pd.DataFrame(rows, columns=HIST_COLS)
    df["date"] = pd.to_datetime(df["date"])
    return df


# --------------------------------------------------------------- market watch
def parse_market_watch(text: str) -> pd.DataFrame:
    rows = []
    for tr in _doc(text).xpath("//tbody/tr"):
        tds = tr.xpath("./td")
        if len(tds) < 11:
            continue
        a = tds[0].xpath(".//a")
        o = [td.get("data-order") for td in tds]
        rows.append({
            "symbol": (tds[0].get("data-search") or _txt(tds[0])).strip(),
            "name": a[0].get("data-title") if a else None,
            "sector_code": _txt(tds[1]),
            "listed_in": _txt(tds[2]),
            "ldcp": to_num(o[3]), "open": to_num(o[4]), "high": to_num(o[5]),
            "low": to_num(o[6]), "current": to_num(o[7]), "change": to_num(o[8]),
            "change_pct": to_num(o[9]), "volume": to_num(o[10]),
        })
    return pd.DataFrame(rows)


# -------------------------------------------------------------------- company
_QUOTE_KEYS = {
    "open": "open", "high": "high", "low": "low", "volume": "volume",
    "ask price": "ask_price", "ask volume": "ask_volume", "bid price": "bid_price",
    "bid volume": "bid_volume", "ldcp": "ldcp", "var": "var", "haircut": "haircut",
    "p/e ratio (ttm)": "pe_ttm", "1-year change": "chg_1y", "ytd change": "chg_ytd",
}
_RANGE_KEYS = {"circuit breaker": "cb", "day range": "day", "52-week range": "wk52"}


def _label_key(label: str) -> str:
    return re.sub(r"[\*\^]+", "", label).strip().lower()


def parse_company(text: str, symbol: str) -> dict:
    """GET /company/{SYM} -> dict with keys info, quote, equity (flat dicts)
    and financials, ratios (long DataFrames)."""
    doc = _doc(text)
    info: dict = {"symbol": symbol, "name": None, "tags": ""}
    name_el = doc.xpath("//div[@class='quote__name']")
    if name_el:
        # name text without the trailing tags (XD, XB, ...)
        info["name"] = (name_el[0].text or "").strip() or _txt(name_el[0])
        info["tags"] = ",".join(_txt(t) for t in name_el[0].xpath(".//div[contains(@class,'tag')]"))
    info["sector"] = _txt(next(iter(doc.xpath("//div[@class='quote__sector']")), None)) or None
    info["price"] = to_num(_txt(next(iter(doc.xpath("//div[@class='quote__close']")), None)))
    info["as_of"] = _txt(next(iter(doc.xpath("//div[@class='quote__date']")), None)).lstrip("^ ").replace("As of ", "")
    heads = doc.xpath("//div[@class='item__head']")
    for h in heads:
        key = _txt(h).lower()
        nxt = h.getnext()
        val = _txt(nxt) if nxt is not None else ""
        if key == "business description":
            info["description"] = val
        elif key == "fiscal year end":
            info["fiscal_year_end"] = val
        elif key in ("auditor", "registrar", "website", "address"):
            info[key] = val

    quote: dict = {"symbol": symbol}
    reg = doc.xpath("//div[contains(@class,'tabs__panel') and @data-name='REG']")
    if reg:
        for item in reg[0].xpath(".//div[@class='stats_item']"):
            lab = item.xpath("./div[@class='stats_label']")
            val = item.xpath("./div[contains(@class,'stats_value')]")
            if not lab or not val:
                continue
            k = _label_key(_txt(lab[0]))
            v = _txt(val[0])
            if k in _RANGE_KEYS:
                lo, hi = _range(v)
                quote[f"{_RANGE_KEYS[k]}_low"], quote[f"{_RANGE_KEYS[k]}_high"] = lo, hi
            elif k in _QUOTE_KEYS:
                quote[_QUOTE_KEYS[k]] = to_num(v)

    equity: dict = {"symbol": symbol}
    eq_title = doc.xpath("//h1[contains(@class,'section__title') and contains(., 'Equity Profile')]")
    if eq_title:
        values = [(_label_key(_txt(i.xpath("./div[@class='stats_label']")[0])),
                   _txt(i.xpath("./div[contains(@class,'stats_value')]")[0]))
                  for i in eq_title[0].getparent().xpath(".//div[@class='stats_item']")
                  if i.xpath("./div[@class='stats_label']")]
        for k, v in values:
            if k.startswith("market cap"):
                equity["market_cap_000"] = to_num(v)
            elif k == "shares":
                equity["shares"] = to_num(v)
            elif k == "free float" and v.endswith("%"):
                equity["free_float_pct"] = to_num(v)
            elif k == "free float":
                equity["free_float_shares"] = to_num(v)

    fin_rows = []
    # exact class match: contains(@class,'tabs__panel') would also hit the
    # 'tabs__panels' wrapper and duplicate the first table
    for panel in doc.xpath("//div[@id='financialTab']//div[contains(concat(' ', normalize-space(@class), ' '),"
                           " ' tabs__panel ')]"):
        kind = (panel.get("data-name") or "").lower()          # annual | quarterly
        fin_rows += _long_table(panel, symbol, kind)
    ratio_rows = []
    rt = doc.xpath("//h1[contains(@class,'section__title') and normalize-space(.)='Ratios']")
    if rt:
        ratio_rows = _long_table(rt[0].getparent(), symbol, "annual")
    cols = ["symbol", "kind", "period", "item", "value"]
    return {"info": info, "quote": quote, "equity": equity,
            "financials": pd.DataFrame(fin_rows, columns=cols),
            "ratios": pd.DataFrame(ratio_rows, columns=cols)}


def _long_table(container, symbol: str, kind: str) -> list[tuple]:
    out = []
    for tbl in container.xpath(".//table")[:1]:
        periods = [_txt(th) for th in tbl.xpath(".//thead//th")][1:]
        for tr in tbl.xpath(".//tbody/tr"):
            tds = tr.xpath("./td")
            if len(tds) < 2:
                continue
            item = _txt(tds[0])
            for p, td in zip(periods, tds[1:]):
                out.append((symbol, kind, p, item, to_num(_txt(td))))
    return out


# -------------------------------------------------------------------- payouts
_PAYOUT_KIND = {"D": "dividend", "B": "bonus", "R": "right"}


def parse_payout_details(s: str) -> list[dict]:
    """'30%(i) (D) - 50% (B)' -> [{kind: dividend, pct: 30, tag: i}, {kind: bonus, pct: 50}]

    PSX enters these by hand, so the format drifts ('50%)F) (D)', '= 12.14 AT A
    PREMIUM RS. 170 PER SHARE (R)'). Anything unparseable keeps kind/amount
    blank; the raw string is always stored alongside.
    """
    out = []
    for seg in re.split(r"\s+-\s+", s or ""):
        seg = seg.strip()
        if not seg:
            continue
        kind = None
        m = re.search(r"\((D|B|R)\)\s*$", seg, re.I)
        if m:
            kind = _PAYOUT_KIND[m.group(1).upper()]
        elif seg.upper().startswith("DIVIDEND"):
            kind = "dividend"
        rec = {"kind": kind, "pct": np.nan, "rs": np.nan, "tag": None, "issue_adj_rs": np.nan}
        body = seg.lstrip("= ").strip()
        mrs = re.match(r"(?i)rs\.?\s*([\d.,]+)", body)
        mnum = re.search(r"([\d.]+)\s*%", body) or re.match(r"(?:DIVIDEND\s*=\s*)?([\d.]+)", body, re.I)
        if mrs:
            rec["rs"] = to_num(mrs.group(1))
        elif mnum:
            rec["pct"] = to_num(mnum.group(1))
        mt = re.search(r"\(?\s*\b(F|I{1,3}|IV|V|i{1,3}|iv|v)\s*\)", body)
        if mt:
            rec["tag"] = mt.group(1).upper()
        mp = re.search(r"(?i)premium\s*(?:of\s*)?rs\.?\s*([\d.]+)", body)
        md = re.search(r"(?i)discount\s*(?:of\s*)?rs\.?\s*([\d.]+)", body)
        if mp:
            rec["issue_adj_rs"] = to_num(mp.group(1))
        elif md:
            rec["issue_adj_rs"] = -to_num(md.group(1))
        out.append(rec)
    return out


def _parse_dt(s: str) -> pd.Timestamp:
    for fmt in ("%B %d, %Y %I:%M %p", "%b %d, %Y %I:%M %p", "%B %d, %Y", "%b %d, %Y"):
        try:
            return pd.Timestamp(datetime.strptime(s.strip(), fmt))
        except ValueError:
            continue
    return pd.NaT


def _parse_dmy(s: str) -> pd.Timestamp:
    try:
        return pd.Timestamp(datetime.strptime(s.strip(), "%d/%m/%Y"))
    except ValueError:
        return pd.NaT


def parse_payouts(text: str) -> pd.DataFrame:
    """POST /payouts (market-wide or per symbol). One row per payout component."""
    rows = []
    for tr in _doc(text).xpath("//tbody/tr"):
        tds = [_txt(td) for td in tr.xpath("./td")]
        if len(tds) != 6:
            continue
        sym, company, sector, details, announced, bc = tds
        bc_from, bc_to = (bc.split("-", 1) + [""])[:2] if bc else ("", "")
        base = {"symbol": sym, "company": company, "sector": sector, "details": details,
                "announced_at": _parse_dt(announced),
                "book_closure_from": _parse_dmy(bc_from), "book_closure_to": _parse_dmy(bc_to)}
        parts = parse_payout_details(details) or [{"kind": None}]
        for i, p in enumerate(parts):
            rows.append({**base, "component": i, **p})
    return pd.DataFrame(rows)


# -------------------------------------------------------------- announcements
def parse_announcements(text: str) -> pd.DataFrame:
    rows = []
    for tr in _doc(text).xpath("//tbody/tr"):
        tds = tr.xpath("./td")
        if len(tds) < 6:
            continue
        pdf = tds[5].xpath(".//a[contains(@href,'.pdf')]/@href")
        imgs = tds[5].xpath(".//a/@data-images")
        doc_id = re.search(r"/(\d+)\.pdf", pdf[0]).group(1) if pdf and re.search(r"/(\d+)\.pdf", pdf[0]) else None
        rows.append({
            "announced_at": _parse_dt(f"{_txt(tds[0])} {_txt(tds[1])}"),
            "symbol": _txt(tds[2]),
            "company": _txt(tds[3]),
            "title": _txt(tds[4]),
            "pdf_url": pdf[0] if pdf else None,
            "doc_id": doc_id,
            "images": ",".join(imgs) if imgs else None,
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------ company reports
def parse_company_reports(text: str, symbol: str) -> pd.DataFrame:
    rows = []
    for tr in _doc(text).xpath("//tbody/tr"):
        tds = tr.xpath("./td")
        if len(tds) < 3:
            continue
        a = tds[0].xpath(".//a")
        url = a[0].get("href") if a else None
        rid = re.search(r"id=([^&]+)", url).group(1) if url and "id=" in url else None
        rows.append({"symbol": symbol, "report_type": _txt(tds[0]),
                     "period": _txt(tds[1]), "posted": pd.to_datetime(_txt(tds[2]), errors="coerce"),
                     "url": url, "report_id": rid})
    return pd.DataFrame(rows).drop_duplicates() if rows else pd.DataFrame(
        columns=["symbol", "report_type", "period", "posted", "url", "report_id"])


# ---------------------------------------------------------------- timeseries
def eod_to_frame(data: list[list], symbol: str, tz: str = "Asia/Karachi") -> pd.DataFrame:
    """[unix_ts, close, volume, open] -> frame keyed by the Karachi trading date."""
    df = pd.DataFrame(data, columns=["ts", "close", "volume", "open"])
    df["date"] = (pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(tz)
                  .dt.tz_localize(None).dt.normalize())
    df["symbol"] = symbol
    return (df[["symbol", "date", "open", "close", "volume"]]
            .sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True))
