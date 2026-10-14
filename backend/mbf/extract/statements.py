"""Extract key unconsolidated statement values from PSX company report PDFs.

Baseline only: pdfplumber / pypdfium2 for text, RapidOCR for image-only pages,
no layout models. Per PDF:

1. Page text from pypdfium2 (milliseconds per page). A page with almost no
   text is treated as scanned.
2. Every page is scored as a candidate statement of financial position (BS)
   or profit and loss (PL): line-item vocabulary and numeric density, minus
   penalties for "consolidated", multi-year summaries ("six years at a
   glance", horizontal/vertical analysis) and notes. A page is only picked
   if a line in its top third IS the title ("Unconsolidated Condensed Interim
   Statement of Financial Position"): notes pages share the vocabulary and
   say "balance sheet" mid-sentence. Matching is done on text with every
   non-letter removed, because text layers (and OCR) often lose spaces:
   "STATEMENTOF FINANCIALPOSITION". When no text page qualifies, scanned
   pages are OCR'd in page order - a layout check and a few title boxes from
   the top quarter first, then the first page with a matching title fully at
   scale 2.5 (OCR costs ~10 s per full statement page on CPU).
3. Selected pages become word boxes (pdfplumber or RapidOCR) and then lines.
   Facing-page spreads (landscape page with an empty gutter) are split into
   two panels, and old-format balance sheets with liabilities on the left
   and assets on the right into two sides; otherwise their lines merge.
   A text layer that is garbled (overprinted, broken encoding) or a balance
   sheet that does not add up is read again with OCR, keeping the better.
4. Figures are right-aligned, so value columns are clusters of the right
   edges of numbers. Small integers left of the first value column are note
   references. The current period is the first value column unless the
   header years say a later column is newer. Quarterly P&Ls have four columns
   (cumulative then quarter); the first, cumulative, one is taken.
5. A section state machine (equity, non-current liabilities, ...) maps labels
   through a synonym table and resolves UNLABELLED subtotals, which is how
   most PSX statements print section totals: a bare number equal to the sum
   of the items above it. The last such subtotal of a section is its total,
   except that a sponsor/holding-company loan printed after the equity
   subtotal stays outside equity (that is how AKD counts it). A section that
   prints no subtotal at all gets the sum of its items.
6. Values are normalised to Rs thousands from the unit in the header
   ("Rupees in '000", "Rupees", "Rs in million"); EPS stays in rupees.

Output is a tidy frame: symbol, report_id, period_end, field_key,
value_thousands, page (1-based), method (text|ocr), label, plus ``how``
(label | subtotal | subtotal? | sum | repeat | derived) for failure analysis.
"""
from __future__ import annotations

import difflib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

OCR_SCALE = 2.5            # full OCR of a selected page
OCR_HEAD_SCALE = 1.4       # title-finding pass on scanned pages
OCR_HEAD_FRACTION = 0.25   # ... on the top quarter only
HEAD_FRACTION = 0.35       # text pages: titles are looked for in the top 35 %
MIN_TEXT_CHARS = 80        # fewer characters than this = image-only page
MIN_SCORE = 6.0
EPS_KEY = "eps"
FIELDS = ["equity", "share_cap", "reserves", "assets", "liabilities", "nc_assets", "c_assets",
          "nc_liabilities", "c_liabilities", "cabb", "st_borr", "lt_debt",
          "sales", "pbt", "pat", "eps"]
COLUMNS = ["symbol", "report_id", "period_end", "field_key", "value_thousands", "page",
           "method", "label", "how"]


# ================================================================== numbers
_DASH = re.compile(r"^[-‐-―_=]+$")
_YEAR = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")


def parse_number(tok: str) -> float | None:
    """One printed figure -> float. '1,234' -> 1234, '(1,234)' -> -1234,
    '-' -> 0 (nil), '(7.33)' -> -7.33. Also tolerates OCR habits: dots as
    thousands separators ('1.240.075.372'), a lost bracket ('(1,234'), a
    'C' read for '('. Returns None for anything that is not a figure."""
    t = tok.strip().replace(" ", "").replace("−", "-")
    if not t:
        return None
    if _DASH.match(t):
        return 0.0
    if re.match(r"^[Cc]\d", t) and t.endswith(")"):
        t = "(" + t[1:]
    neg = False
    if t.startswith("(") or t.endswith(")"):
        neg = True
        t = t.strip("()")
    if t.startswith("-"):
        neg = True
        t = t[1:]
    t = t.rstrip(",.")
    if not re.fullmatch(r"\d[\d,.]*", t):
        return None
    if t.count(".") > 1:                                   # 1.240.075 -> thousands groups
        parts = re.split(r"[.,]", t)
        if not all(len(p) == 3 for p in parts[1:]):
            return None
        t = "".join(parts)
    elif "," in t and "." in t and t.rfind(",") > t.rfind("."):   # 1.234,5 never used here
        return None
    if "," in t and not re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", t):
        return None                     # '218,,232488,,098495': a garbled text layer, not a figure
    t = t.replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


_OCR_DIGITS = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "i": "1",
                             "|": "1", "!": "1", "B": "8", "S": "5", "s": "5", "Z": "2", "z": "2"})


def clean_ocr_number(tok: str) -> str:
    """OCR habits in figures: square/curly brackets for round ones, letters for
    look-alike digits ('(B8,113,415)'), and a comma read as a dot ('80.331').
    Only touches tokens that are mostly digits already; labels pass through."""
    t = tok.translate(str.maketrans("[{]}", "(())"))
    core = re.sub(r"[()\-.,]", "", t)
    if core and not core.isdigit() and sum(c.isdigit() for c in core) >= max(2, 0.7 * len(core)):
        t = t.translate(_OCR_DIGITS)
    if re.fullmatch(r"\(?\d{1,3}\.\d{3}\)?", t):     # statement figures are whole numbers
        t = t.replace(".", ",")
    return t


def _is_value_like(tok: str) -> bool:
    """A token that can only be a statement figure (used to find columns):
    separators, brackets, decimals or 4+ digits. Small bare integers may be
    note references and are left out; so are bare years."""
    t = tok.strip()
    if parse_number(t) is None or _DASH.match(t) or _is_note(t):
        return False                      # '5.1' is a note; EPS '6.59' is placed later by position
    if re.fullmatch(r"(19[89]\d|20[0-4]\d)", t):
        return False
    return bool(re.search(r"[,.()]", t)) or len(re.sub(r"\D", "", t)) >= 4


def _is_note(tok: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}(\.\d{1,2})*(\s*[&,]\s*\d{1,2}(\.\d{1,2})*)*", tok.strip()))


# ================================================================== units
_COMPACT = re.compile(r"[\s\"`‘’“”]+")
# "(Rupees in '000)", "Rs. 000", "(Amounts in thousand except EPS)", "PKR in million"
_THOUS = re.compile(r"((rupees?|rs|pkr)\.?|amounts?(are)?(stated)?)(in)?(pak)?(rupees?|rs|pkr)?\(?'?([0o]{3}|thousand)")
_MILL = re.compile(r"((rupees?|rs|pkr)\.?|amounts?(are)?(stated)?)(in)?(pak)?(rupees?|rs|pkr)?\(?(million|mln|mn\b)")
_RUPEE_HDR = re.compile(r"^\(?\s*((note|amount|in|\(?un-?\s*audited\)?|\(?audited\)?|"
                        r"restated|rupees|rs\.?|pkr)\s*\)?\s*)+$")


def detect_unit(text: str) -> tuple[float | None, str]:
    """Factor that converts the page's figures to Rs thousands, from header
    phrases such as "(Rupees in '000)", "Rs. in thousand", "Rupees in million"
    or a bare "Rupees" column header. (None, '') when nothing is printed."""
    low = text.lower()
    compact = _COMPACT.sub("", low).replace("’", "'")
    if _THOUS.search(compact) or re.search(r"\(\s*'000\s*\)|in\s*'000", low):
        return 1.0, "thousands"
    if _MILL.search(compact):
        return 1000.0, "millions"
    for line in low.splitlines():
        s = _COMPACT.sub(" ", re.sub(r"[-_=.–—…:]{2,}", " ", line)).strip()
        if s and re.search(r"rupees|\brs\b|pkr", s) and _RUPEE_HDR.match(s):
            return 0.001, "rupees"
    if re.search(r"\(\s*(rupees|rs\.?)\s*\)|amounts?\s+in\s+(pak\s+)?(rupees|pkr)\b(?!\s*(in\s*)?'?(000|thousand|million))",
                 low):
        return 0.001, "rupees"
    return None, ""


def guess_unit(values: list[float]) -> tuple[float, str]:
    """No unit printed: statements in full rupees show 9-12 digit figures,
    statements in thousands rarely exceed 8."""
    big = [abs(v) for v in values if abs(v) >= 1000]
    if not big:
        return 1.0, "thousands?"
    return (0.001, "rupees?") if np.median(big) > 5e6 else (1.0, "thousands?")


# ================================================================== labels
def squash(s: str) -> str:
    """Lower case letters only: robust to lost spaces, punctuation, OCR noise."""
    return re.sub(r"[^a-z]", "", s.lower())


SECTION_HEADERS: list[tuple[str, re.Pattern]] = [
    ("equity", re.compile(r"^(total)?(shareholders|members)?(equityandliabilities|capitalandliabilities)$")),
    ("equity", re.compile(r"^(sharecapitalandreserves?|capitalandreserves?|equity|shareholdersequity|"
                          r"shareholdersfunds|equityandreserves|issuedcapitalandreserves|"
                          r"capitalandreservesattributable\w*)$")),
    ("nc_liabilities", re.compile(r"^non?currentliabilit(y|ies)$")),
    ("c_liabilities", re.compile(r"^currentliabilit(y|ies)$")),
    ("nc_assets", re.compile(r"^non?currentassets$")),
    ("c_assets", re.compile(r"^currentassets$")),
    ("assets_top", re.compile(r"^(assets|propertyandassets)$")),
    ("liabilities_top", re.compile(r"^liabilities$")),
    ("end", re.compile(r"^contingenc(y|ies)andcommitments?$")),
]

# (field_key, pattern on squashed label, exclusion pattern, allowed sections or None = anywhere)
BS_SYNONYMS: list[tuple[str, str, str | None, set | None]] = [
    ("eq_liab", r"^total(equityandliabilities|liabilitiesandequity|capitalandliabilities|"
                r"shareholdersequityandliabilities)", None, None),
    ("equity", r"^total(shareholders|shareholder|stockholders|members|owners)?s?equity$|"
               r"^(shareholders|stockholders)s?equity$|^totalequityattributable|"
               r"^total(share)?capitalandreserves?$|^netequity$", "liabilit", None),
    ("share_cap", r"(issued|subscribed|paidup).*capital|^(ordinary)?sharecapital", "authori[sz]ed", None),
    ("reserves", r"^(total)?reserves$|^capitalandrevenuereserves$", None, None),
    ("assets", r"^totalassets$", None, None),
    ("liabilities", r"^totalliabilities$", None, None),
    ("nc_assets", r"^totalnon?currentassets$", None, None),
    ("c_assets", r"^totalcurrentassets$", None, None),
    ("nc_liabilities", r"^totalnon?currentliabilities$", None, None),
    ("c_liabilities", r"^totalcurrentliabilities$", None, None),
    ("cabb", r"^cash(inhand)?and(cash)?(at|with)?banks?|^cashandcashequivalents$|^bankbalances|"
             r"^cashatbanks?$|^cashandbank", None, {"c_assets", "assets_top", None}),
    ("st_borr", r"shortterm(borrowing|financ|loan|runningfinanc|murabaha)|runningfinanc|"
                r"^borrowings?$|financesundermarkuparrangement|^shorttermborrowings",
     r"currentportion|accrued|^markup|^interest|^profit|payable", {"c_liabilities", "liabilities_top", None}),
    ("lt_debt", r"^longterm(financ|loan|borrowing|debt)|^(loans?|financing)frombank|"
                r"termfinancecertificate|sukuk|^redeemablecapital",
     r"currentportion|deposit|accrued|^markup|receivable|lease|advances?$", {"nc_liabilities", "liabilities_top", None}),
]
TOTAL_KEYS = {"equity", "assets", "liabilities", "nc_assets", "c_assets", "nc_liabilities",
              "c_liabilities", "eq_liab"}
SECTION_TOTAL = {"equity": "equity", "nc_liabilities": "nc_liabilities", "c_liabilities": "c_liabilities",
                 "nc_assets": "nc_assets", "c_assets": "c_assets"}
_LOANISH = re.compile(r"loan|subordinat|sponsor|director|holdingcompany")

PL_SYNONYMS: list[tuple[str, str, str | None]] = [
    ("sales", r"^(net)?(sales|revenue|revenues|turnover)(fromoperations|fromcontracts?withcustomers?)?(net)?$|"
              r"^revenuefromcontracts?withcustomers?|^salesrevenue|^netrevenue",
     r"cost|gross|tax|duty|discount|local|export|commission"),
    ("pbt", r"(profit|loss|income|earning|result)\w*before\w*tax|^before\w*tax", r"operating"),
    ("pat", r"(profit|loss|income|earning)\w*(af?t?ertax|for(the)?(year|period|quarter|halfyear|"
            r"ninemonths|sixmonths|threemonths))|^net(profit|loss|income)",
     r"comprehensive|before|attributable|operating|gross|^(income)?tax|pershare|levy|levies"),
    ("eps", r"(earning|loss|profit|income)s?\w*pershare", None),
]


# Canonical spellings for a fuzzy second chance when the regexes miss an
# OCR-misspelt label ('Current Liabitities', 'Cash and bankbalanccs').
_FUZZY_SECTIONS = {"noncurrentliabilities": "nc_liabilities", "currentliabilities": "c_liabilities",
                   "noncurrentassets": "nc_assets", "currentassets": "c_assets",
                   "sharecapitalandreserves": "equity", "equityandliabilities": "equity",
                   "contingenciesandcommitments": "end"}
_FUZZY_BS = {"issuedsubscribedandpaidupsharecapital": "share_cap", "issuedsubscribedandpaidupcapital": "share_cap",
             "sharecapital": "share_cap", "totalequity": "equity", "totalassets": "assets",
             "totalliabilities": "liabilities", "totalcurrentassets": "c_assets",
             "totalnoncurrentassets": "nc_assets", "totalcurrentliabilities": "c_liabilities",
             "totalnoncurrentliabilities": "nc_liabilities", "totalequityandliabilities": "eq_liab",
             "cashandbankbalances": "cabb", "cashandcashequivalents": "cabb", "shorttermborrowings": "st_borr",
             "shorttermfinances": "st_borr", "longtermfinancing": "lt_debt", "longtermfinances": "lt_debt",
             "longtermloans": "lt_debt"}
_FUZZY_PL = {"salesnet": "sales", "netsales": "sales", "revenuenet": "sales", "netrevenue": "sales",
             "turnovernet": "sales", "profitbeforetaxation": "pbt", "lossbeforetaxation": "pbt",
             "profitaftertaxation": "pat", "lossaftertaxation": "pat", "profitfortheperiod": "pat",
             "lossfortheperiod": "pat", "profitfortheyear": "pat", "lossfortheyear": "pat",
             "earningspershare": "eps", "losspershare": "eps", "earningspersharebasicanddiluted": "eps"}


def _fuzzy(sq: str, table: dict[str, str], cutoff: float = 0.88) -> str | None:
    if len(sq) < 6:
        return None
    best = difflib.get_close_matches(sq, table.keys(), n=1, cutoff=cutoff)
    return table[best[0]] if best else None


def section_header(sq: str) -> str | None:
    for sec, pat in SECTION_HEADERS:
        if pat.match(sq):
            return sec
    return _fuzzy(sq, _FUZZY_SECTIONS)


def map_label(label: str, statement: str = "bs", section: str | None = None) -> str | None:
    """Label -> field_key via the synonym tables, then a fuzzy match on a few
    canonical spellings; None if it is not a field we keep."""
    sq = squash(label)
    if not sq:
        return None
    if statement == "pl":
        for key, pat, excl in PL_SYNONYMS:
            if re.search(pat, sq) and not (excl and re.search(excl, sq)):
                return key
        return _fuzzy(sq, _FUZZY_PL)
    for key, pat, excl, secs in BS_SYNONYMS:
        if secs is not None and section not in secs:
            continue
        if re.search(pat, sq) and not (excl and re.search(excl, sq)):
            return key
    key = _fuzzy(sq, _FUZZY_BS)
    secs = next((s for k, _, _, s in BS_SYNONYMS if k == key), None)
    if key and (secs is None or section in secs):
        return key
    return None


# ================================================================== page geometry
@dataclass
class Word:
    x0: float
    x1: float
    top: float
    bottom: float
    text: str


@dataclass
class Line:
    label: str
    values: list[float | None]
    top: float
    bottom: float
    page: int
    method: str
    years: list[tuple[float, int]] = field(default_factory=list)
    cur: int = 0                 # index of the current-period column
    factor: float = 1.0          # multiplier to Rs thousands

    @property
    def has_values(self) -> bool:
        return any(v is not None for v in self.values)


def _merge_fragments(ws: list[Word]) -> list[Word]:
    """Re-join figures split by a stray space: '( 961,657,992)', '1 ,098,933'."""
    out: list[Word] = []
    for w in ws:
        if out:
            p = out[-1]
            gap = w.x0 - p.x1
            h = max(p.bottom - p.top, 4.0)
            joins = (re.fullmatch(r"\(?-?\d{1,3}(,\d{3})*,?", p.text) and re.match(r"^[,.]\d{3}", w.text)) \
                or (p.text in ("(", "-(") and re.match(r"^\d", w.text))
            # '4 86,613,872': a leading digit split off; only when the join is a valid grouping
            split_digit = re.fullmatch(r"\(?\d", p.text) and re.match(r"^\d{1,2},\d{3}", w.text) \
                and len(re.sub(r"\D", "", p.text) + w.text.split(",")[0]) <= 3 and gap < 0.6 * h
            if (joins and gap < 1.2 * h) or split_digit:
                out[-1] = Word(p.x0, w.x1, min(p.top, w.top), max(p.bottom, w.bottom), p.text + w.text)
                continue
        out.append(w)
    return out


def group_lines(words: list[Word]) -> list[list[Word]]:
    if not words:
        return []
    hs = sorted(w.bottom - w.top for w in words)
    tol = max(2.0, 0.5 * hs[len(hs) // 2])
    lines: list[list[Word]] = []
    centre: list[float] = []
    for w in sorted(words, key=lambda w: ((w.top + w.bottom) / 2, w.x0)):
        c = (w.top + w.bottom) / 2
        if lines and abs(c - centre[-1]) <= tol:
            lines[-1].append(w)
            centre[-1] = np.mean([(x.top + x.bottom) / 2 for x in lines[-1]])
        else:
            lines.append([w])
            centre.append(c)
    return [_merge_fragments(sorted(ln, key=lambda w: w.x0)) for ln in lines]


def _columns(lines: list[list[Word]], tol: float) -> list[float]:
    xs = sorted(w.x1 for ln in lines for w in ln if _is_value_like(w.text))
    clusters: list[list[float]] = []
    for x in xs:
        if clusters and x - np.mean(clusters[-1]) <= tol:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    cols = [float(np.median(c)) for c in clusters if len(c) >= 3]
    # merge columns that drifted apart by a little more than tol
    merged: list[float] = []
    for c in cols:
        if merged and c - merged[-1] < 1.6 * tol:
            continue
        merged.append(c)
    return merged


def split_panels(words: list[Word], width: float, height: float) -> list[list[Word]]:
    """Facing-page spreads: split at the gutter when nothing crosses the middle,
    unless one half is mostly figures - then it is a wide single statement
    with labels on the left and its figure columns on the right."""
    if width <= 1.15 * height or not words:
        return [words]
    mid = width / 2
    crossing = sum(1 for w in words if w.x0 < mid - 3 and w.x1 > mid + 3)
    left = [w for w in words if (w.x0 + w.x1) / 2 < mid]
    right = [w for w in words if (w.x0 + w.x1) / 2 >= mid]

    def figures_only(ws):
        return sum(_is_value_like(w.text) for w in ws) >= 0.6 * len(ws)

    if crossing <= 2 and len(left) > 5 and len(right) > 5 and not figures_only(left) \
            and not figures_only(right):
        return [left, right]
    return [words]


def split_side_by_side(words: list[Word], method: str) -> list[list[Word]]:
    """Old-format balance sheets print equity and liabilities on the left and
    assets on the right of one portrait page, each side with its own label
    and two figure columns. Labels sitting between figure columns on many
    lines give it away; split there and read each side on its own."""
    raw = group_lines(words)
    tol = 14.0 if method == "text" else 20.0
    cols = _columns(raw, tol)
    if len(cols) < 4:
        return [words]
    for k in range(1, len(cols) - 2):
        lo, hi = cols[k] + tol, cols[k + 1] - 3 * tol
        n = sum(1 for ln in raw
                if sum(1 for w in ln if lo < w.x0 < hi and re.search(r"[A-Za-z]{3}", w.text)) >= 2)
        if n >= 6:
            cut = cols[k] + tol / 2
            left = [w for w in words if w.x1 <= cut]
            right = [w for w in words if w.x1 > cut]
            return [left, right]
    return [words]


def build_lines(words: list[Word], page: int, method: str) -> list[Line]:
    """Words -> lines with a label and one value per detected column."""
    if method == "ocr":
        words = [Word(w.x0, w.x1, w.top, w.bottom, clean_ocr_number(w.text)) for w in words]
    raw = group_lines(words)
    tol = 14.0 if method == "text" else 20.0
    cols = _columns(raw, tol)
    out: list[Line] = []
    if not cols:
        return [Line(" ".join(w.text for w in ln), [], min(w.top for w in ln),
                     max(w.bottom for w in ln), page, method) for ln in raw]
    # left edge of each column, from the widest figures in it: small figures
    # such as EPS are often centred in the column rather than right-aligned
    lefts = []
    for j, c in enumerate(cols):
        xs = [w.x0 for ln in raw for w in ln if _is_value_like(w.text) and abs(w.x1 - c) <= 1.6 * tol]
        lefts.append(max(float(np.percentile(xs, 25)) if xs else c - 40, cols[j - 1] + tol if j else -1e9))
    for ln in raw:
        values: list[float | None] = [None] * len(cols)
        label_words: list[str] = []
        years: list[tuple[float, int]] = []
        for w in ln:
            v = parse_number(w.text)
            ym = _YEAR.search(w.text)
            if ym and not re.search(r"\d,\d", w.text):
                years.append((w.x1, int(ym.group(1))))
                if re.fullmatch(r"\(?(19[89]\d|20[0-4]\d)\)?", w.text):
                    continue                      # a bare year is a header, never a figure
            in_figures = w.x1 > lefts[0] - tol / 2 and not (_is_note(w.text) and w.x0 < lefts[0] - tol / 2)
            if v is not None and in_figures:
                j = int(np.argmin([abs(w.x1 - c) for c in cols]))
                if abs(w.x1 - cols[j]) <= 1.6 * tol and values[j] is None:
                    values[j] = v
                    continue
                span = [k for k in range(len(cols)) if lefts[k] - tol / 2 <= w.x0 and w.x1 <= cols[k] + tol]
                centred_ok = _is_value_like(w.text) or re.fullmatch(r"\(?-?\d+\.\d{2}\)?", w.text) \
                    or _DASH.match(w.text)                # never a bare note number
                if span and centred_ok and values[span[0]] is None:
                    values[span[0]] = v
                    continue
            if v is not None and w.x1 >= cols[0] - tol:
                continue                          # stray number in the figure area
            label_words.append(w.text)
        while label_words and (_is_note(label_words[-1]) or label_words[-1] in {"-", "Note", "note"}):
            label_words.pop()
        out.append(Line(" ".join(label_words).strip(), values, min(w.top for w in ln),
                        max(w.bottom for w in ln), page, method, years))
    return _drop_junk_columns(out)


def _drop_junk_columns(lines: list[Line]) -> list[Line]:
    """A 'column' of single digits next to real figures is debris from a
    garbled text layer (or stray note numbers), not a period column."""
    ncol = max((len(ln.values) for ln in lines), default=0)
    med = []
    for j in range(ncol):
        vals = [abs(ln.values[j]) for ln in lines if j < len(ln.values) and ln.values[j]]
        med.append(float(np.median(vals)) if len(vals) >= 3 else None)
    junk = {j for j, m in enumerate(med) if m is not None and m < 10
            and any(o is not None and o > 1000 for o in med)}
    if junk:
        for ln in lines:
            ln.values = [v for j, v in enumerate(ln.values) if j not in junk]
    return lines


def current_column(lines: list[Line]) -> int:
    """Index of the current-period column: the one under the latest year in
    the header, ties (Dec-2020 vs Jun-2020) going to the leftmost."""
    ncol = max((len(ln.values) for ln in lines), default=0)
    for ln in lines:
        if ln.has_values and squash(ln.label):
            break                                  # header is above the first item
        if len(ln.years) >= 2 and ncol >= 2:
            # columns carry no positions here; years are left-to-right like the columns
            ys = [y for _, y in sorted(ln.years)][-ncol:]
            if ys and ys[0] < max(ys):
                return ys.index(max(ys))
            return 0
    return 0


def _join_wrapped(lines: list[Line]) -> list[Line]:
    """Multi-line labels: a figure-less line continues into the next line when
    it ends with a connector or the next label starts in lower case; a lower
    case figure-less line right after a figure line is that line's tail."""
    out: list[Line] = []
    i = 0
    connector = re.compile(r"(\band|\bof|\bfor|\bto|\bon|\bin|\bthe|\bfrom|\bunder|&|,|-|/)\s*$", re.I)
    while i < len(lines):
        ln = lines[i]
        if not ln.has_values and ln.label and i + 1 < len(lines):
            nx = lines[i + 1]
            h = max(ln.bottom - ln.top, 4.0)
            close = nx.top - ln.bottom < 1.0 * h
            if nx.has_values and close and section_header(squash(ln.label)) is None and \
                    (connector.search(ln.label) or (nx.label[:1].islower())):
                lines[i + 1] = Line(f"{ln.label} {nx.label}".strip(), nx.values, ln.top, nx.bottom,
                                    nx.page, nx.method, nx.years)
                i += 1
                continue
        if ln.has_values and i + 1 < len(lines):
            nx = lines[i + 1]
            h = max(ln.bottom - ln.top, 4.0)
            if not nx.has_values and nx.label[:1].islower() and nx.top - ln.bottom < 0.8 * h \
                    and section_header(squash(nx.label)) is None:
                ln = Line(f"{ln.label} {nx.label}".strip(), ln.values, ln.top, nx.bottom, ln.page,
                          ln.method, ln.years)
                out.append(ln)
                i += 2
                continue
        out.append(ln)
        i += 1
    return out


# ================================================================== page scoring
_BS_TITLE = re.compile(r"statementoffinancialposition|balancesheet")
_PL_TITLE = re.compile(r"profitandlossaccount|profitorlossaccount|statementofprofitorloss|"
                       r"statementofprofitandloss|incomestatement|profitandloss(?!andother)|"
                       r"statementofprofit")
_OTHER_TITLE = re.compile(r"cashflow|changesinequity|statementofchanges|notestothe|directorsreport|"
                          r"chairmansreview|auditorsreport|reviewreport")
_SUMMARY = re.compile(r"ataglance|horizontalanalysis|verticalanalysis|sixyears|tenyears|"
                      r"financialhighlights|keyfigures|keyoperating|yearsataglance|summaryoffinancial|"
                      r"analysisoffinancial|dupont|quarterlyperformance")
_BS_WORDS = ["sharecapital", "currentliabilities", "currentassets", "totalassets", "equityandliabilities",
             "tradeandotherpayables", "propertyplantandequipment", "cashandbank", "stockintrade",
             "deferred", "unappropriated"]
_PL_WORDS = ["costofsales", "costofrevenue", "grossprofit", "grossloss", "beforetax", "pershare",
             "financecost", "administrativeexpenses", "distribution", "taxation", "otherincome",
             "otheroperating"]
_FIGURE = re.compile(r"\(?\d{1,3}(?:,\d{3})+\)?")


def _consolidated(sq: str) -> int:
    return len(re.findall(r"(?<!un)consolidated", sq))


def _head(text: str, n: int = 10) -> str:
    return squash(" ".join([ln for ln in text.splitlines() if ln.strip()][:n]))


_TITLE_PREFIX = r"^((un)?consolidated|condensed|interim|unaudited|standalone|separate|the|and)*"
_TITLE_LINE = {"bs": re.compile(_TITLE_PREFIX + r"(statementoffinancialposition|"
                                                r"balancesheet($|asat|unaudited|audited))"),
               "pl": re.compile(_TITLE_PREFIX + r"(statementofprofit|profitandlossaccount|profitorlossaccount|"
                                                r"incomestatement|profitandloss($|account|statement|forthe))"),
               "pl_weak": re.compile(_TITLE_PREFIX + r"statementofcomprehensiveincome")}


def title_strength(text: str, kind: str, region: bool = False) -> int:
    """2 when a line near the top IS the statement title (optionally prefixed
    by 'unconsolidated condensed interim'), 1 for a bare 'statement of
    comprehensive income' (a P&L in some filings, OCI only in others), else 0.
    Notes pages carry the same vocabulary and figures, and mention 'balance
    sheet' mid-sentence, so a page without a title line is never picked alone."""
    best = 0
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # region=True: text cut from the top of the page, every line counts.
    # Otherwise the first lines, and the last ones (some PDFs store the page
    # header last in the content stream).
    for part in ([lines[:80]] if region else (lines[:12], lines[-14:])):
        for i, ln in enumerate(part):
            # a title may wrap: 'UNCONSOLIDATED STATEMENT OF' / 'FINANCIAL POSITION'
            for sq in (squash(ln), squash(ln + " " + part[i + 1]) if i + 1 < len(part) else ""):
                if not sq or len(sq) > 110:
                    continue
                if _TITLE_LINE[kind].match(sq) or _fuzzy_title(sq, kind):
                    return 2
                if kind == "pl" and _TITLE_LINE["pl_weak"].match(sq):
                    best = 1
    return best


_CANON_TITLES = {"bs": ["statementoffinancialposition", "balancesheet"],
                 "pl": ["statementofprofitorloss", "profitandlossaccount", "statementofprofitandloss",
                        "incomestatement"]}


def _fuzzy_title(sq: str, kind: str) -> bool:
    """OCR drops or swaps letters in titles ('STATEMENTOFRNANCIALPOSITION')."""
    rest = re.sub(_TITLE_PREFIX, "", sq)
    if not re.match(r"(stat|bala|prof|inco)", rest):        # cheap gate: difflib is slow
        return False
    for c in _CANON_TITLES[kind]:
        m = difflib.SequenceMatcher(None, rest[:len(c)], c)
        if m.quick_ratio() >= 0.88 and m.ratio() >= 0.88:
            return True
    return False


def has_title(text: str, kind: str, region: bool = False) -> bool:
    return title_strength(text, kind, region) > 0


def score_page(text: str, kind: str, head_text: str | None = None) -> float:
    """How much a page looks like the unconsolidated BS (kind='bs') or P&L
    ('pl'). ``head_text`` is the text in the top part of the page, where the
    title is looked for (defaults to the first lines of ``text``)."""
    region = head_text is not None
    ht = head_text if region else text
    head = _head(ht)
    sq = squash(text)
    figures = len(_FIGURE.findall(text))
    s = 0.0
    if kind == "bs":
        s += 6 if has_title(ht, "bs", region) else (1.5 if _BS_TITLE.search(sq) else 0)
        s += sum(1 for w in _BS_WORDS if w in sq)
        if has_title(ht, "pl", region) or ("pershare" in sq and not has_title(ht, "bs", region)):
            s -= 4
    else:
        s += {2: 6, 1: 3}.get(title_strength(ht, "pl", region), 1.5 if _PL_TITLE.search(sq) else 0)
        s += sum(1 for w in _PL_WORDS if w in sq)
        if has_title(ht, "bs", region):
            s -= 4
    s += 2 if figures >= 20 else (0 if figures >= 8 else -10)
    if _consolidated(sq):
        s -= 8
    if "unconsolidated" in sq:
        s += 1
    if _SUMMARY.search(squash(ht) if region else _head(text, 15)):
        s -= 10                           # judged on the top: some text layers hide whole other pages
    if _OTHER_TITLE.search(head):
        s -= 6
    return s


# ================================================================== OCR
_ENGINE = None


def _ocr_engine():
    """RapidOCR with the bundled PP-OCRv4 models. Detection limits the LONG
    side (2000 px) instead of RapidOCR's default of upscaling the short side
    to 736 px, which made a strip cropped from the top of a page 7x slower."""
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR(det_limit_type="max", det_limit_side_len=2000)
    return _ENGINE


def _render(page, scale: float) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(page.render(scale=scale).to_pil().convert("RGB"))[:, :, ::-1])


def ocr_words(page, scale: float = OCR_SCALE) -> list[Word]:
    """Render with pypdfium2 and OCR the whole page (no angle classifier: pages
    are upright and it costs a third of the time). Coordinates in PDF points."""
    res, _ = _ocr_engine()(_render(page, scale), use_cls=False)
    words: list[Word] = []
    for box, text, _conf in res or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        words.extend(_split_box(min(xs) / scale, max(xs) / scale, min(ys) / scale, max(ys) / scale, text))
    return words


def ocr_head(page, scale: float = OCR_HEAD_SCALE, fraction: float = OCR_HEAD_FRACTION,
             max_boxes: int = 4) -> str:
    """Cheap title pass for scanned pages: detect text in the top strip, then
    recognise only the first few short boxes. Recognition is ~95 % of OCR
    time and grows with line width, so body paragraphs are skipped."""
    eng = _ocr_engine()
    try:
        # prose and picture pages are skipped on layout alone (detection is
        # ~0.1 s): a statement has a column of short boxes on its right half
        small = _render(page, 1.0)
        boxes, _ = eng.text_det(small)
        if boxes is None:
            return ""
        w = small.shape[1]
        figures = sum(1 for b in boxes if b[:, 0].min() > 0.5 * w
                      and (b[:, 0].max() - b[:, 0].min()) < 8 * max(b[:, 1].max() - b[:, 1].min(), 1))
        if figures < 10:
            return ""
        img = _render(page, scale)
        img = np.ascontiguousarray(img[: int(img.shape[0] * fraction)])
        boxes, _ = eng.text_det(img)
        if boxes is None or len(boxes) == 0:
            return ""
        keep = []
        for b in eng.sorted_boxes(boxes):
            w = np.linalg.norm(b[0] - b[1])
            h = max(np.linalg.norm(b[0] - b[3]), 1.0)
            if w / h <= 40:
                keep.append(b)
            if len(keep) == max_boxes:
                break
        if not keep:
            return ""
        rec, _ = eng.text_rec(eng.get_crop_img_list(img, keep), False)
        return "\n".join(r[0] for r in rec)
    except AttributeError:                    # RapidOCR internals moved: fall back to the public call
        res, _ = eng(img, use_cls=False)
        return "\n".join(r[1] for r in (res or [])[:max_boxes])


def _split_box(x0: float, x1: float, top: float, bottom: float, text: str) -> list[Word]:
    """One box holding several space-separated tokens -> one Word per token,
    x positions shared out by character count (right edges stay usable)."""
    n = len(text)
    out: list[Word] = []
    for m in re.finditer(r"\S+", text):
        a = x0 + (x1 - x0) * m.start() / max(n, 1)
        b = x0 + (x1 - x0) * m.end() / max(n, 1)
        out.append(Word(a, b, top, bottom, m.group()))
    return out


def decode_cid(text: str) -> str:
    return re.sub(r"\(cid:(\d+)\)", lambda m: chr(int(m.group(1))) if 32 <= int(m.group(1)) < 127 else "",
                  text)


def _words_text(words: list[Word]) -> str:
    return "\n".join(" ".join(w.text for w in ln) for ln in group_lines(words))


# ================================================================== statements
@dataclass
class Hit:
    key: str
    value: float
    label: str
    page: int
    method: str
    how: str


def parse_balance(lines: list[Line]) -> dict[str, Hit]:
    """Section state machine over the BS lines (already in reading order)."""
    found: dict[str, Hit] = {}
    cands: dict[str, list[tuple[Hit, bool]]] = {}   # section -> [(subtotal, loan_item_before)]
    unverified: dict[str, Hit] = {}
    summed: dict[str, Hit] = {}                      # sections that print no closing subtotal
    section: str | None = None
    stack: list[float] = []
    loan_since = False
    repeats: list[float] = []
    last: Line | None = None
    heading: str | None = None

    def close_section():
        """No subtotal at all -> the sum of the items. Items after the last
        subtotal (PPE subtotalled, then investments and deferred tax listed
        bare) -> that subtotal was a group, the section total is the sum."""
        tk = SECTION_TOTAL.get(section or "")
        if not (tk and stack and last is not None) or tk in found or tk in summed:
            return
        # not for equity: old formats list the revaluation surplus after the equity total
        after_group = tk != "equity" and bool(cands.get(tk)) and len(stack) > 1 \
            and stack[0] == cands[tk][-1][0].value
        if after_group or (not cands.get(tk) and tk not in unverified):
            summed[tk] = Hit(tk, sum(stack), "(sum of section items, no closing subtotal)", last.page,
                             last.method, "sum")
            if after_group:
                cands.pop(tk)
                unverified.pop(tk, None)

    def put(k: str, h: Hit):
        if k not in found:
            found[k] = h

    def resolved(k: str) -> float | None:
        if k in found:
            return found[k].value
        c = _pick(cands.get(k, []))
        return c.value if c else (unverified[k].value if k in unverified else None)

    for ln in lines:
        sq = squash(ln.label)
        cur = ln.values[ln.cur] if ln.values and ln.cur < len(ln.values) else None
        sec = section_header(sq)
        if sec and (cur is None or cur == 0 or sec == "end"):
            close_section()
            section = None if sec == "end" else sec
            stack, loan_since = [], False
            continue
        if cur is None:
            # 'Issued, subscribed and paid up capital' as a heading, figure on the next line
            h = "share_cap" if map_label(ln.label, "bs", section) == "share_cap" else \
                ("memo" if re.search(r"authori[sz]ed", sq) else None)
            heading = h or heading                    # survives '14,958,000 ordinary shares...' lines
            continue
        last = ln
        repeats.append(cur)
        tol = max(2.0 + len(stack), 1e-4 * abs(cur))
        if re.search(r"authori[sz]ed|ordinaryshares?of", sq) and not re.search(r"issued|paidup|subscri", sq):
            if heading == "share_cap" and not re.search(r"authori[sz]ed", sq):
                # '... ordinary shares of Rs 10 each' under an 'Issued...' heading
                put("share_cap", Hit("share_cap", cur, ln.label, ln.page, ln.method, "label"))
                stack.append(cur)
            heading = None
            continue                                  # otherwise authorised capital, a memo line
        if heading == "memo" and len(sq) < 3:
            heading = None
            continue                                  # the authorised capital figure itself
        if heading == "share_cap" and len(sq) < 3:
            put(heading, Hit(heading, cur, "(figure under share capital heading)", ln.page, ln.method, "label"))
            heading = None
            stack.append(cur)
            continue
        heading = None
        if len(sq) >= 3:
            key = map_label(ln.label, "bs", section)
            if key:
                put(key, Hit(key, cur, ln.label, ln.page, ln.method, "label"))
            if key in TOTAL_KEYS:
                stack = [cur]
            else:
                stack.append(cur)
                if section == "equity" and _LOANISH.search(sq) and not re.search(r"reserve|capital", sq):
                    loan_since = True
            continue
        # ---- an unlabelled figure: a subtotal or a grand total
        tk = SECTION_TOTAL.get(section or "")
        if stack and abs(sum(stack) - cur) <= tol:
            if tk:
                cands.setdefault(tk, []).append(
                    (Hit(tk, cur, "(unlabelled subtotal)", ln.page, ln.method, "subtotal"), loan_since))
                loan_since = False
            stack = [cur]
            continue
        nca, ca = resolved("nc_assets"), resolved("c_assets")
        eq, ncl, cl = resolved("equity"), resolved("nc_liabilities"), resolved("c_liabilities")
        if nca is not None and ca is not None and abs(nca + ca - cur) <= tol:
            put("assets", Hit("assets", cur, "(unlabelled total)", ln.page, ln.method, "subtotal"))
            stack = [cur]
            continue
        if None not in (eq, ncl, cl) and abs(eq + ncl + cl - cur) <= tol:
            put("eq_liab", Hit("eq_liab", cur, "(unlabelled total)", ln.page, ln.method, "subtotal"))
            stack = [cur]
            continue
        for k in range(len(stack) - 1, 1, -1):          # a group inside the section
            if abs(sum(stack[-k:]) - cur) <= tol:
                stack = stack[:-k] + [cur]
                if tk and tk not in unverified:           # or the total, if a stray line came first
                    unverified[tk] = Hit(tk, cur, "(unlabelled, partial sum)", ln.page, ln.method,
                                         "subtotal?")
                break
        else:
            if tk and tk not in unverified and not cands.get(tk):
                unverified[tk] = Hit(tk, cur, "(unlabelled, sum unchecked)", ln.page, ln.method, "subtotal?")
                stack = [cur]

    close_section()
    for k in SECTION_TOTAL.values():
        if k not in found:
            c = _pick(cands.get(k, []))
            if c is not None:
                found[k] = c
            elif k in unverified:
                found[k] = unverified[k]
            elif k in summed:
                found[k] = summed[k]
    _derive_bs(found, repeats, lines)
    return found


def _pick(cands: list[tuple[Hit, bool]]) -> Hit | None:
    """Last subtotal of a section, unless a loan line sits before a later one
    (sponsor loans printed under equity are not equity)."""
    if not cands:
        return None
    best = cands[0][0]
    for h, loan_before in cands[1:]:
        if loan_before:
            break
        best = h
    return best


def _derive_bs(found: dict[str, Hit], repeats: list[float], lines: list[Line]):
    def d(k, v, how_label):
        pg = lines[0].page if lines else 0
        mt = lines[0].method if lines else "text"
        found[k] = Hit(k, v, how_label, pg, mt, "derived")

    if "assets" not in found:
        if "eq_liab" in found:
            d("assets", found["eq_liab"].value, "derived: = total equity and liabilities")
        elif "nc_assets" in found and "c_assets" in found:
            d("assets", found["nc_assets"].value + found["c_assets"].value, "derived: nc_assets + c_assets")
        else:
            big = sorted({v for v in repeats if repeats.count(v) >= 2 and v > 0}, reverse=True)
            if big:
                h = Hit("assets", big[0], "(largest figure printed twice)", lines[0].page,
                        lines[0].method, "repeat")
                found["assets"] = h
    if "liabilities" not in found and "nc_liabilities" in found and "c_liabilities" in found:
        d("liabilities", found["nc_liabilities"].value + found["c_liabilities"].value,
          "derived: nc_liabilities + c_liabilities")
    if "liabilities" not in found and "nc_liabilities" not in found and "c_liabilities" in found \
            and "equity" in found and "assets" in found:
        e, cl, a = found["equity"].value, found["c_liabilities"].value, found["assets"].value
        if abs(e + cl - a) <= 2 + 1e-4 * abs(a):          # no non-current liabilities at all
            d("liabilities", cl, "derived: = c_liabilities (equity + current = assets)")
            d("nc_liabilities", 0.0, "derived: none (equity + current = assets)")
    if "equity" not in found and "assets" in found and "liabilities" in found:
        d("equity", found["assets"].value - found["liabilities"].value, "derived: assets - liabilities")
    if "nc_assets" not in found and "assets" in found and "c_assets" in found:
        d("nc_assets", found["assets"].value - found["c_assets"].value, "derived: assets - c_assets")
    if "c_assets" not in found and "assets" in found and "nc_assets" in found:
        d("c_assets", found["assets"].value - found["nc_assets"].value, "derived: assets - nc_assets")


def parse_income(lines: list[Line]) -> dict[str, Hit]:
    """First matching line per field. Among the sales lines above cost of
    sales a 'net' one wins (gross sales, less duties, net sales), and so does
    a bare subtotal right after 'Less: sales tax' lines. An 'Earnings per
    share' heading without figures hands over to a 'Basic' line below it, or
    to the bare total under per-segment lines ('Refinery operations ...').
    Profit 'from continuing / refinery operations' gives way to a later
    'profit for the year' total."""
    found: dict[str, Hit] = {}
    sales: list[Hit] = []
    seen_cost = eps_pending = deducting = False
    deductions: list[float] = []
    eps_parts = 0
    for ln in lines:
        cur = ln.values[ln.cur] if ln.values and ln.cur < len(ln.values) else None
        sq = squash(ln.label)
        key = map_label(ln.label, "pl")
        if cur is None:
            eps_pending = key == "eps" or (eps_pending and not sq)
            eps_parts = 0
            seen_cost = seen_cost or "costof" in sq
            continue
        if key is None and eps_pending:
            if re.fullmatch(r"(basic|diluted|basicanddiluted|basicanddilutive|dilutedandbasic)?", sq):
                key = "eps"
            elif "operation" in sq and eps_parts < 3:        # per-segment EPS, total follows
                eps_parts += 1
                continue
        eps_pending = False
        if key == "pat" and "pat" in found and "from" in squash(found["pat"].label) and "from" not in sq:
            found["pat"] = Hit("pat", cur, ln.label, ln.page, ln.method, "label")
            continue
        if sales and not seen_cost and re.match(r"less|salestax|discount|commission|excise|duty|rebate", sq):
            deductions = (deductions if deducting else []) + [abs(cur)]
            deducting = True
            continue
        if deducting and not seen_cost and len(sq) < 3:
            gross = sales[-1].value
            if abs(abs(cur) - (gross - sum(deductions))) <= 2 + 1e-4 * abs(gross):
                sales.append(Hit("sales", cur, "net sales (gross less deductions)", ln.page, ln.method,
                                 "subtotal"))
                deducting = False
            elif abs(abs(cur) - sum(deductions)) <= 2 + 1e-4 * abs(gross):
                deductions = [abs(cur)]                 # a subtotal of the deductions themselves
            continue
        deducting = False
        hit = Hit(key or "", cur, ln.label, ln.page, ln.method, "label")
        if key == "sales" and (not seen_cost or not sales):
            sales.append(hit)
        elif key == "eps" and abs(cur) > 5000:
            pass                                     # a misread figure, not a per-share amount
        elif key and key != "sales" and key not in found:
            found[key] = hit
        seen_cost = seen_cost or "costof" in sq
    if sales:
        net = [h for h in sales if "net" in squash(h.label) or h.how == "subtotal"]
        found["sales"] = net[0] if net else sales[0]
    return found


# ================================================================== document
@dataclass
class Panel:
    page: int
    method: str
    words: list[Word]
    text: str
    width: float
    height: float


@dataclass
class DocInfo:
    pages: int = 0
    image_pages: int = 0
    kind: str = ""
    bs_pages: list[int] = field(default_factory=list)
    pl_pages: list[int] = field(default_factory=list)
    bs_method: str = ""
    pl_method: str = ""
    unit: str = ""
    ocr_pages: int = 0
    seconds: float = 0.0
    error: str = ""


Unit = tuple[int, "int | None"]     # (page index, half of a spread or None)


class _Doc:
    """Lazy access to one PDF through both libraries. Landscape pages also get
    the text of each half, so a spread holding the BS on the left and the P&L
    on the right is scored as two units."""

    def __init__(self, path: Path):
        import pdfplumber
        import pypdfium2 as pdfium
        self.path = path
        self.pdfium = pdfium.PdfDocument(str(path))
        self.plumber = pdfplumber.open(str(path))
        self.n = len(self.pdfium)
        self.texts: list[str] = []
        self.half_texts: dict[Unit, str] = {}
        # text physically in the top third: titles are searched there, because
        # content-stream order can put a page header last or after a sidebar
        self.heads: dict[Unit, str] = {}
        for i in range(self.n):
            pg = self.pdfium[i]
            tp = pg.get_textpage()
            self.texts.append(tp.get_text_range())
            w, h = pg.get_size()
            top = HEAD_FRACTION
            if pg.get_rotation() == 0:
                self.heads[(i, None)] = tp.get_text_bounded(0, h * (1 - top), w, h)
            if w > 1.15 * h and pg.get_rotation() == 0:
                self.half_texts[(i, 0)] = tp.get_text_bounded(0, 0, w / 2, h)
                self.half_texts[(i, 1)] = tp.get_text_bounded(w / 2, 0, w, h)
                self.heads[(i, 0)] = tp.get_text_bounded(0, h * (1 - top), w / 2, h)
                self.heads[(i, 1)] = tp.get_text_bounded(w / 2, h * (1 - top), w, h)
            tp.close()
        self.ocr_cache: dict[int, list[Word]] = {}
        self.head_cache: dict[int, str] = {}
        self.ocr_pages = 0
        self.garbled_text = False

    def close(self):
        self.plumber.close()
        self.pdfium.close()

    def is_image(self, i: int) -> bool:
        """No usable text layer: (almost) no text, or a font without a usable
        encoding that comes out as control characters - read those by OCR."""
        t = self.texts[i]
        if len(re.sub(r"\s", "", t)) < MIN_TEXT_CHARS or len(re.findall(r"[A-Za-z]", t)) < 40:
            return True
        return len(re.findall(r"[\x00-\x08\x0b\x0e-\x1f]", t)) > 0.1 * len(t)

    def reading_units(self) -> list[Unit]:
        out: list[Unit] = []
        for i in range(self.n):
            out.extend([(i, 0), (i, 1)] if (i, 0) in self.half_texts else [(i, None)])
        return out

    def unit_text(self, u: Unit) -> str:
        return self.texts[u[0]] if u[1] is None else self.half_texts[u]

    def unit_head(self, u: Unit) -> str:
        return self.heads.get(u) or self.unit_text(u)

    def score(self, u: Unit, kind: str) -> float:
        return score_page(self.unit_text(u), kind, self.heads.get(u))

    def titled(self, u: Unit, kind: str) -> bool:
        return has_title(self.heads[u], kind, True) if u in self.heads else has_title(self.unit_text(u), kind)

    def size(self, i: int) -> tuple[float, float]:
        w, h = self.pdfium[i].get_size()
        if self.pdfium[i].get_rotation() in (90, 270):
            w, h = h, w
        return w, h

    def text_words(self, i: int) -> list[Word]:
        """pdfplumber words. Fonts without a Unicode map come out as
        '(cid:72)(cid:65)...'; in PSX filings those codes are plain ASCII
        (pypdfium2 reads the same pages fine), so decode and re-split them."""
        out: list[Word] = []
        for w in self.plumber.pages[i].extract_words(x_tolerance=1.5, y_tolerance=2.5,
                                                     keep_blank_chars=False):
            if "(cid:" in w["text"]:
                out.extend(_split_box(w["x0"], w["x1"], w["top"], w["bottom"], decode_cid(w["text"])))
            else:
                out.append(Word(w["x0"], w["x1"], w["top"], w["bottom"], w["text"]))
        return out

    def ocr(self, i: int) -> list[Word]:
        if i not in self.ocr_cache:
            self.ocr_cache[i] = ocr_words(self.pdfium[i], OCR_SCALE)
            self.ocr_pages += 1
        return self.ocr_cache[i]

    def ocr_head(self, i: int) -> str:
        if i not in self.head_cache:
            self.head_cache[i] = ocr_head(self.pdfium[i])
        return self.head_cache[i]

    def panels(self, i: int, method: str) -> list[Panel]:
        if method == "text" and self.plumber.pages[i].rotation in (90, 270):
            method = "ocr"            # pdfplumber keeps unrotated coordinates; the render is upright
        words = self.text_words(i) if method == "text" else self.ocr(i)
        w, h = self.size(i)
        return [Panel(i, method, p, _words_text(p), w, h) for p in split_panels(words, w, h)]


def _neighbour_needed(text: str, kind: str) -> list[str]:
    """What the main BS unit lacks and a continuation should supply."""
    sq = squash(text)
    if kind != "bs":
        return []
    need = []
    if "currentassets" not in sq:
        need.append("currentassets")
    if "currentliabilities" not in sq and "sharecapital" not in sq:
        need.append("currentliabilities")
    return need


def _locate(doc: _Doc, kind: str) -> tuple[list[Unit], str]:
    """Units holding the statement and how they will be read (text|ocr)."""
    reading = doc.reading_units()
    cands = [u for u in reading if not doc.is_image(u[0])]
    cands += [(i, None) for (i, h) in reading if h == 0 and not doc.is_image(i)]
    scored = sorted(((doc.score(u, kind), u) for u in cands),
                    key=lambda t: (-t[0], t[1][0], -1 if t[1][1] is None else t[1][1]))
    titled = [t for t in scored if doc.titled(t[1], kind)]
    if titled and titled[0][0] >= MIN_SCORE:
        best = titled[0][1]
        return _with_neighbours(reading, best, kind, doc.unit_text, lambda u: not doc.is_image(u[0])), "text"
    units, method = _locate_ocr(doc, kind)
    if units:
        return units, method
    if scored and scored[0][0] >= MIN_SCORE + 4:       # untitled but unmistakable
        return _with_neighbours(reading, scored[0][1], kind, doc.unit_text,
                                lambda u: not doc.is_image(u[0])), "text"
    return [], ""


def _locate_ocr(doc: _Doc, kind: str) -> tuple[list[Unit], str]:
    """OCR fallback, in page order: a cheap title pass on each scanned page,
    full OCR to confirm, stop at the first confirmed page (the unconsolidated
    statements come before the consolidated ones in PSX reports)."""
    best, tried = None, 0
    for i in (i for i in range(doc.n) if doc.is_image(i)):
        head = doc.ocr_head(i)
        h = squash(head)
        if _consolidated(h) or _SUMMARY.search(h):
            continue
        if not has_title(head, kind, True) and not _title_runs_over(doc, i, head, kind):
            continue
        tried += 1
        if score_page(_words_text(doc.ocr(i)), kind) >= MIN_SCORE - 2:
            best = i
            break
        if tried >= 5:
            break
    if best is None:
        return [], ""
    pages = [(i, None) for i in range(doc.n)]
    return _with_neighbours(pages, (best, None), kind, lambda u: _words_text(doc.ocr(u[0])),
                            lambda u: doc.is_image(u[0])), "ocr"


def _title_runs_over(doc: _Doc, i: int, head: str, kind: str) -> bool:
    """A spread scanned as two pages splits its title too: 'CONDENSED INTERIM
    STATEMENT OF' on the left page, 'FINANCIAL POSITION' on the right."""
    tails = [ln for ln in head.splitlines() if squash(ln).endswith("statementof")]
    if not tails or i + 1 >= doc.n or not doc.is_image(i + 1):
        return False
    return any(has_title(t + " " + m, kind, True) for t in tails for m in doc.ocr_head(i + 1).splitlines())


def _with_neighbours(reading: list[Unit], best: Unit, kind: str, text_of, same_kind) -> list[Unit]:
    """Add the next unit when the BS continues there (liabilities on one page,
    assets on the next)."""
    units = [best]
    need = _neighbour_needed(text_of(best), kind)
    if not need:
        return units
    if best in reading:
        k = reading.index(best) + 1
    else:                                         # a whole spread: continue after its right half
        k = reading.index((best[0], 1)) + 1
    if k < len(reading) and same_kind(reading[k]):
        nxt = text_of(reading[k])
        head = squash(" ".join(nxt.splitlines()[:6]))
        if any(n in squash(nxt) for n in need) and not _PL_TITLE.search(head) \
                and not _OTHER_TITLE.search(head) and not _consolidated(head):
            units.append(reading[k])
    return units


def garbled_share(words: list[Word]) -> float:
    """Share of figure-like tokens that do not parse. Clean text layers are
    near 0; overprinted or badly encoded layers ('218,,232488,,098495')
    are far above, and are better read from the rendered page."""
    toks = [w.text for w in words if re.fullmatch(r"[\d,.()\-]+", w.text) and len(re.sub(r"\D", "", w.text)) >= 3]
    if len(toks) < 10:
        return 0.0
    return sum(parse_number(t) is None for t in toks) / len(toks)


def bs_quality(hits: dict[str, Hit]) -> int:
    """Fields found directly (not derived) plus 3 for each balance identity
    that holds: nc + current assets = total assets; equity + liabilities =
    total equity and liabilities (or total assets)."""
    v = {k: h.value for k, h in hits.items() if h.how != "derived"}
    q = sum(k in v for k in ("equity", "assets", "nc_assets", "c_assets", "nc_liabilities",
                             "c_liabilities", "share_cap"))

    def close(a, b):
        return abs(a - b) <= 2 + 1e-4 * abs(b)

    if all(k in v for k in ("nc_assets", "c_assets", "assets")) and close(v["nc_assets"] + v["c_assets"], v["assets"]):
        q += 3
    total = v.get("eq_liab", v.get("assets"))
    if total is not None and all(k in v for k in ("equity", "nc_liabilities", "c_liabilities")) \
            and close(v["equity"] + v["nc_liabilities"] + v["c_liabilities"], total):
        q += 3
    return q


def _statement_lines(doc: _Doc, units: list[Unit], method: str, kind: str
                     ) -> tuple[list[Line], str, float]:
    out: list[Line] = []
    words_seen: list[Word] = []
    unit_name = ""
    factor = None
    for i, half in units:
        panels = doc.panels(i, method)
        if len(panels) == 2 and half is not None:
            panels = [panels[half]]
        elif len(panels) > 1:                            # keep the half that holds the statement
            words = _BS_WORDS if kind == "bs" else _PL_WORDS
            hits = [sum(1 for w in words if w in squash(p.text)) for p in panels]
            panels = [p for p, n in zip(panels, hits) if n >= 2] or [panels[int(np.argmax(hits))]]
        for p in panels:
            words_seen.extend(p.words)
            f, u = detect_unit("\n".join(p.text.splitlines()[:15]))
            if f is None:
                f, u = detect_unit(p.text)
            if f is None and factor is not None:
                f, u = factor, unit_name
            for side in split_side_by_side(p.words, p.method):
                lines = _join_wrapped(build_lines(side, i + 1, p.method))
                cur = current_column(lines)
                fs, us = (f, u) if f is not None else \
                    guess_unit([v for ln in lines for v in ln.values if v is not None])
                factor, unit_name = fs, us
                for ln in lines:
                    ln.cur = cur
                    ln.factor = fs
                out.extend(lines)
    return out, unit_name, garbled_share(words_seen)


def _read_statement(doc: _Doc, units: list[Unit], method: str, kind: str
                    ) -> tuple[list[Line], str, dict[str, Hit], str]:
    """Parse the statement; when the text layer is garbled or the balance
    sheet does not add up, read the same pages again with OCR and keep
    whichever result is better."""
    parse = parse_balance if kind == "bs" else parse_income
    lines, unit, bad = _statement_lines(doc, units, method, kind)
    hits = parse(lines)
    if method != "text":
        return lines, unit, hits, method
    garbled = bad > 0.15 or doc.garbled_text           # one garbled statement taints the file
    doc.garbled_text = garbled
    weak = garbled or (bs_quality(hits) < 7 if kind == "bs" else len(hits) < 3)
    if not weak:
        return lines, unit, hits, method
    lines2, unit2, _ = _statement_lines(doc, units, "ocr", kind)
    hits2 = parse(lines2)
    better = bs_quality(hits2) > bs_quality(hits) if kind == "bs" else \
        (len(hits2) > len(hits) or (garbled and len(hits2) >= len(hits)))
    log.info("text layer weak for %s (garbled %.0f%%), OCR retry %s", kind, 100 * bad,
             "kept" if better else "discarded")
    return (lines2, unit2, hits2, "ocr") if better else (lines, unit, hits, method)


BS_FIELDS = {"equity", "share_cap", "reserves", "assets", "liabilities", "nc_assets", "c_assets",
             "nc_liabilities", "c_liabilities", "cabb", "st_borr", "lt_debt"}


def check_units(rows: list[dict], guessed_bs: bool = False) -> str:
    """EPS is printed in rupees whatever unit the statements use, so EPS
    against profit per share exposes a unit misread by 1,000x (an OCR'd
    "Rupees in '000" read as "Rupees"). Shares are taken as share capital /
    Rs 10 par; Rs 5 or Rs 1 par moves the ratio 2-10x, far from 1,000x. The
    P&L is corrected, unless the BS unit was only guessed."""
    v = {r["field_key"]: r["value_thousands"] for r in rows}
    if not all(v.get(k) for k in ("eps", "pat", "share_cap")):
        return ""
    ratio = abs(v["eps"] / (10 * v["pat"] / v["share_cap"]))
    fix = 1000.0 if 100 < ratio < 10000 else (0.001 if 1e-4 < ratio < 1e-2 else None)
    if fix is None:
        return ""
    target = BS_FIELDS if guessed_bs else {"sales", "pbt", "pat"}
    factor = 1 / fix if guessed_bs else fix
    for r in rows:
        if r["field_key"] in target:
            r["value_thousands"] *= factor
    return f"{'bs' if guessed_bs else 'pl'} x{factor:g} by EPS check"


def extract(pdf_path: str | Path, symbol: str = "", report_id: str = "",
            period_end=None) -> tuple[pd.DataFrame, DocInfo]:
    """Extract one PDF. Never raises on a bad PDF: the error goes into DocInfo."""
    t0 = time.monotonic()
    info = DocInfo()
    rows: list[dict] = []
    doc = None
    try:
        doc = _Doc(Path(pdf_path))
        info.pages = doc.n
        info.image_pages = sum(doc.is_image(i) for i in range(doc.n))
        share = info.image_pages / max(doc.n, 1)
        info.kind = "scanned" if share >= 0.8 else ("text" if share <= 0.2 else "mixed")
        units = []
        for kind in ("bs", "pl"):
            found_units, method = _locate(doc, kind)
            if not found_units:
                log.info("%s: no %s page found", report_id or pdf_path, kind)
                continue
            lines, unit, hits, method = _read_statement(doc, found_units, method, kind)
            units.append(f"{kind}:{unit}")
            setattr(info, f"{kind}_pages", sorted({u[0] + 1 for u in found_units}))
            setattr(info, f"{kind}_method", method)
            fac = {ln.page: ln.factor for ln in lines}
            for k, h in hits.items():
                if k not in FIELDS:
                    continue
                v = h.value if k == EPS_KEY else h.value * fac.get(h.page, 1.0)
                rows.append({"symbol": symbol, "report_id": report_id, "period_end": period_end,
                             "field_key": k, "value_thousands": v, "page": h.page,
                             "method": h.method, "label": h.label, "how": h.how})
        fixed = check_units(rows, guessed_bs=any(u.startswith("bs:") and u.endswith("?") for u in units))
        info.unit = " ".join(units) + (f" ({fixed})" if fixed else "")
        info.ocr_pages = doc.ocr_pages
    except Exception as e:                       # a broken PDF must not stop a batch
        log.exception("%s: extraction failed", report_id or pdf_path)
        info.error = f"{type(e).__name__}: {e}"
    finally:
        if doc is not None:
            doc.close()
    info.seconds = time.monotonic() - t0
    return pd.DataFrame(rows, columns=COLUMNS), info
