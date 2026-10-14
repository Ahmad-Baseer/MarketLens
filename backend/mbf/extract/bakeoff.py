"""Bake-off: run the statement extractor on a fixed sample and score it against AKD.

    python -m mbf.extract.bakeoff sample      pick the sample (seed 7) and print it
    python -m mbf.extract.bakeoff download    fetch the sampled PDFs (2 s apart)
    python -m mbf.extract.bakeoff run         extract + score, write CSVs and tables

Sample. Only reports whose period AKD also covers with at least equity, assets
and share capital. Financial-sector layouts (banks, insurers, modarabas, funds,
leasing, investment banks) are excluded. A (symbol, period) with more than one
PDF is skipped: those are almost always an annual report split into parts or a
re-upload, and we cannot tell which part holds the statements. Annual reports
are listed by fiscal year only, so they are matched to the AKD Q4 row whose
period_end falls in that calendar year and before the posting date.

Scoring. AKD balance-sheet values are period-end and compared directly. AKD
income values are quarter-only (Q4 is derived), while PDFs show cumulative
figures (and often the quarter as well), so an income value counts as a match
if it agrees with either the AKD quarter or the AKD year-to-date sum. That makes
income agreement a looser, secondary check. "Agree" means within 0.5 %, or
within one display unit (Rs 1,000 for statement lines, Rs 0.01 for EPS).
Where AKD repeats a key at the same period_end under two fiscal-year labels
(~0.4 % of keys, the second holding a later period's figures), the majority
year at that date is kept.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from mbf import config, store

log = logging.getLogger(__name__)

SEED = 7
N_PER_TYPE = 20
MAX_PER_SECTOR = 3
YEARS = (2019, 2025)
REQUIRED = ("equity", "assets", "share_cap")
EXCLUDED_SECTORS = {
    "COMMERCIAL BANKS", "INSURANCE", "MODARABAS", "CLOSE - END MUTUAL FUND",
    "EXCHANGE TRADED FUNDS", "BILLS AND BONDS", "INV. BANKS / INV. COS. / SECURITIES COS.",
    "LEASING COMPANIES", "REAL ESTATE INVESTMENT TRUST", "",
}
PDF_DIR = config.DATA_DIR / "raw" / "reports"
OUT_DIR = config.DATA_DIR / "research" / "extract"
BALANCE_KEYS = ["equity", "share_cap", "reserves", "assets", "liabilities", "nc_assets",
                "c_assets", "nc_liabilities", "c_liabilities", "cabb", "st_borr", "lt_debt"]
INCOME_KEYS = ["sales", "pbt", "pat", "eps"]
KEYS = BALANCE_KEYS + INCOME_KEYS
MAX_DOWNLOADS = 40
DOWNLOAD_INTERVAL = 2.0


# ------------------------------------------------------------------ ground truth
def load_akd() -> pd.DataFrame:
    a = pd.read_parquet(config.DATA_DIR / "seed" / "akd" / "statements.parquet",
                        columns=["symbol", "stype", "year", "quarter", "period_end",
                                 "field_key", "value"])
    a = a[a.field_key.isin(KEYS)].dropna(subset=["value"]).copy()
    a["quarter"] = a["quarter"].astype(str).str.strip()
    return a


def _akd_periods(akd: pd.DataFrame) -> pd.DataFrame:
    b = akd[(akd.stype == "balance") & akd.field_key.isin(REQUIRED)]
    n = b.groupby(["symbol", "period_end", "quarter"]).field_key.nunique().reset_index()
    return n[n.field_key == len(REQUIRED)][["symbol", "period_end", "quarter"]]


def eligible(akd: pd.DataFrame | None = None) -> pd.DataFrame:
    akd = load_akd() if akd is None else akd
    rep = pd.read_parquet(config.DATA_DIR / "fundamentals" / "reports.parquet")
    sec = pd.read_parquet(config.DATA_DIR / "ref" / "symbols.parquet", columns=["symbol", "sector"])
    rep = rep.merge(sec, on="symbol", how="inner")
    rep["sector"] = rep["sector"].fillna("").str.strip()
    rep = rep[~rep.sector.isin(EXCLUDED_SECTORS)]
    # one PDF per (symbol, type, period) only
    rep = rep[~rep.duplicated(["symbol", "report_type", "period"], keep=False)]
    per = _akd_periods(akd)

    q = rep[rep.report_type == "Quarterly"].copy()
    q["period_end"] = pd.to_datetime(q.period, errors="coerce")
    q = q.merge(per, on=["symbol", "period_end"])

    a = rep[rep.report_type == "Annual"].copy()
    a["py"] = pd.to_numeric(a.period, errors="coerce")
    p4 = per[per.quarter == "Q4"].assign(py=lambda d: d.period_end.dt.year)
    a = a.merge(p4, on=["symbol", "py"])
    a = a[a.period_end <= a.posted].drop(columns="py")
    a = a.sort_values("period_end").drop_duplicates(["symbol", "period"], keep="last")

    out = pd.concat([q, a], ignore_index=True)
    return out[out.period_end.dt.year.between(*YEARS)].reset_index(drop=True)


def build_sample(seed: int = SEED) -> pd.DataFrame:
    """Shuffle the eligible pool with a fixed seed, then take reports in that order
    under quotas: 20 per report type, at most 3 per sector, one per symbol."""
    pool = eligible().sort_values(["symbol", "report_type", "period"]).reset_index(drop=True)
    pool = pool.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    picked, n_type, n_sec, syms = [], {}, {}, set()
    for i, r in pool.iterrows():
        if n_type.get(r.report_type, 0) >= N_PER_TYPE or n_sec.get(r.sector, 0) >= MAX_PER_SECTOR \
                or r.symbol in syms:
            continue
        picked.append(i)
        n_type[r.report_type] = n_type.get(r.report_type, 0) + 1
        n_sec[r.sector] = n_sec.get(r.sector, 0) + 1
        syms.add(r.symbol)
        if len(picked) == 2 * N_PER_TYPE:
            break
    s = pool.loc[picked, ["symbol", "sector", "report_type", "period", "period_end", "quarter",
                          "posted", "report_id", "url"]]
    return s.sort_values(["report_type", "symbol"]).reset_index(drop=True)


# ------------------------------------------------------------------ download
class DownloadBlocked(RuntimeError):
    pass


def download(sample: pd.DataFrame, dest: Path = PDF_DIR, limit: int = MAX_DOWNLOADS) -> dict:
    """Sequential, one request every 2 s, skip files already on disk. Anything
    that is not a PDF (error status, HTML challenge page) stops the run."""
    import httpx
    dest.mkdir(parents=True, exist_ok=True)
    got, skipped = [], []
    last = 0.0
    with httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=120.0,
                      follow_redirects=True) as http:
        for r in sample.itertuples():
            p = dest / f"{r.report_id}.pdf"
            if p.exists() and p.stat().st_size > 0:
                skipped.append(r.report_id)
                continue
            if len(got) >= limit:
                break
            wait = DOWNLOAD_INTERVAL - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            resp = http.get(r.url)
            ctype = resp.headers.get("content-type", "")
            if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
                raise DownloadBlocked(f"{r.report_id}: HTTP {resp.status_code} {ctype!r}, "
                                      f"{len(resp.content)} bytes, starts {resp.content[:60]!r}")
            tmp = p.with_suffix(".part")
            tmp.write_bytes(resp.content)
            tmp.replace(p)
            got.append(r.report_id)
            log.info("downloaded %s (%s, %.1f MB)", r.report_id, r.symbol, len(resp.content) / 1e6)
    return {"downloaded": got, "skipped": skipped}


# ------------------------------------------------------------------ scoring
def truth_table(akd: pd.DataFrame, sample: pd.DataFrame) -> pd.DataFrame:
    """AKD values for each sampled report: balance at period_end, income both
    as the quarter and as the fiscal year-to-date sum (NaN when a quarter of
    the year is missing in AKD)."""
    rows = []
    for r in sample.itertuples():
        a = akd[akd.symbol == r.symbol]
        here = a[a.period_end == r.period_end]
        if here.empty:
            continue
        # ~0.4 % of AKD keys repeat with a second fiscal-year label and other
        # figures (a later period filed under this date); keep the majority year
        year = int(here.year.mode().iloc[0])
        here = here[here.year == year]
        qn = int(str(r.quarter).lstrip("Q") or 0)
        for k in KEYS:
            hk = here[here.field_key == k]
            if hk.empty:
                continue
            v = float(hk.value.iloc[0])
            ytd = np.nan
            if k in INCOME_KEYS and 1 <= qn <= 4:
                fy = a[(a.year == year) & (a.field_key == k) & (a.stype == "income")]
                fy = fy.drop_duplicates("quarter").set_index("quarter").value
                need = [f"Q{i}" for i in range(1, qn + 1)]
                if all(q in fy.index for q in need):
                    ytd = float(fy.loc[need].sum())
            rows.append({"report_id": r.report_id, "field_key": k, "akd": v, "akd_ytd": ytd,
                         "n_q": qn})
    return pd.DataFrame(rows)


def agrees(x: float, truth: float, unit: float) -> bool:
    if pd.isna(x) or pd.isna(truth):
        return False
    return abs(x - truth) <= max(0.005 * abs(truth), unit + 1e-9)


def score(extracted: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """One row per (report, field) that AKD has, with the extracted value (if
    any) and whether it agrees. EPS unit is Rs 0.01 (0.01 per summed quarter
    for the year-to-date comparison, which adds up rounded quarterly EPS)."""
    m = truth.merge(extracted[["report_id", "field_key", "value_thousands", "method", "how",
                               "label", "page"]], on=["report_id", "field_key"], how="left")
    m["extracted"] = m.value_thousands.notna()
    out = []
    for r in m.itertuples():
        unit = 0.01 if r.field_key == "eps" else 1.0
        out.append((agrees(r.value_thousands, r.akd, unit),
                    agrees(r.value_thousands, r.akd_ytd, unit * max(r.n_q, 1))))
    m["match_q"] = [a for a, _ in out]
    m["match_ytd"] = [b for _, b in out]
    m["match"] = m.match_q | m.match_ytd
    m["stype"] = np.where(m.field_key.isin(BALANCE_KEYS), "balance", "income")
    return m


def field_table(scored: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    g = [by, "field_key"] if by else ["field_key"]
    t = scored.groupby(g).agg(akd=("akd", "size"), extracted=("extracted", "sum"),
                              matches=("match", "sum")).reset_index()
    t["coverage"] = t.extracted / t.akd
    t["agreement"] = t.matches / t.extracted.where(t.extracted > 0)
    t["accuracy"] = t.matches / t.akd
    t["_o"] = t.field_key.map({k: i for i, k in enumerate(KEYS)})
    t = t.sort_values(([by] if by else []) + ["_o"]).drop(columns="_o")
    return t.reset_index(drop=True)


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float) and c in ("coverage", "agreement", "accuracy", "share"):
                cells.append("" if pd.isna(v) else f"{v:.0%}")
            elif isinstance(v, float):
                cells.append("" if pd.isna(v) else f"{v:,.1f}")
            else:
                cells.append(str(v))
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + rows)


def run(sample: pd.DataFrame | None = None, out_dir: Path = OUT_DIR) -> dict:
    from mbf.extract.statements import extract
    sample = build_sample() if sample is None else sample
    akd = load_akd()
    parts, docs = [], []
    for i, r in enumerate(sample.itertuples(), 1):
        p = PDF_DIR / f"{r.report_id}.pdf"
        if not p.exists():
            log.warning("%s missing, run download first", p.name)
            continue
        df, info = extract(p, r.symbol, r.report_id, r.period_end)
        parts.append(df)
        d = dict(info.__dict__)
        d.update(report_id=r.report_id, symbol=r.symbol, report_type=r.report_type, sector=r.sector,
                 fields=len(df))
        docs.append(d)
        log.info("[%d/%d] %s %s %s: %d fields, %s/%s, %.1fs", i, len(sample), r.report_id, r.symbol,
                 r.report_type, len(df), info.bs_method or "-", info.pl_method or "-", info.seconds)
    extracted = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    docs = pd.DataFrame(docs)
    truth = truth_table(akd, sample)
    scored = score(extracted, truth)
    scored = scored.merge(sample[["report_id", "symbol", "report_type"]], on="report_id", how="left")
    out_dir.mkdir(parents=True, exist_ok=True)
    sample.to_csv(out_dir / "sample.csv", index=False)
    extracted.to_csv(out_dir / "extracted.csv", index=False)
    scored.to_csv(out_dir / "scored.csv", index=False)
    docs.to_csv(out_dir / "docs.csv", index=False)
    return {"sample": sample, "extracted": extracted, "scored": scored, "docs": docs}


def summary(res: dict) -> str:
    """Markdown tables for the report."""
    sc, docs = res["scored"].copy(), res["docs"]
    meth = docs.set_index("report_id")
    # text vs OCR by how the statement page was read; a field never extracted
    # counts under the method of its statement (or 'not found')
    sc["read_as"] = [r.method if isinstance(r.method, str) else
                     (meth.loc[r.report_id, "bs_method" if r.stype == "balance" else "pl_method"]
                      or "not found") for r in sc.itertuples()]
    out = ["### Per field (all PDFs)", _md(field_table(sc)), "",
           "### Per field, by how the statement page was read", _md(field_table(sc, "read_as")), "",
           "### Per field, by report type", _md(field_table(sc, "report_type")), ""]
    k = docs.kind.value_counts().rename_axis("kind").reset_index(name="pdfs")
    out += ["### PDFs by text layer", _md(k), ""]
    m = pd.concat([docs.bs_method.replace("", "not found").value_counts().rename("bs"),
                   docs.pl_method.replace("", "not found").value_counts().rename("pl")], axis=1)
    out += ["### Statement pages read as",
            _md(m.fillna(0).astype(int).rename_axis("method").reset_index()), ""]
    t = docs.groupby("kind").seconds.agg(["count", "mean", "median", "max"]).reset_index()
    out += ["### Seconds per PDF", _md(t), f"\nAll: mean {docs.seconds.mean():.1f}s, "
            f"median {docs.seconds.median():.1f}s, total {docs.seconds.sum():.0f}s", ""]
    h = sc[sc.extracted].groupby("how").agg(n=("match", "size"), matches=("match", "sum")).reset_index()
    h["agreement"] = h.matches / h.n
    out += ["### Agreement by how the value was found", _md(h), ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m mbf.extract.bakeoff")
    ap.add_argument("command", choices=["sample", "download", "run"])
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    s = build_sample()
    if a.command == "sample":
        with pd.option_context("display.width", 200, "display.max_rows", 100):
            print(s.drop(columns="url"))
        print(s.report_type.value_counts().to_dict(), "sectors:", s.sector.nunique())
    elif a.command == "download":
        try:
            print(download(s))
        except DownloadBlocked as e:
            log.error("download stopped: %s", e)
            return 1
    else:
        print(summary(run(s)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
