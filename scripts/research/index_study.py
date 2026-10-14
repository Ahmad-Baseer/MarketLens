"""Index recomposition event study: KSE-100 / KSE-30 / KMI-30 additions & deletions."""
import sys; sys.path.insert(0, "backend")
import pandas as pd, numpy as np
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
from mbf.research import eventstudy as es, rights
ALIAS = {"Attock Cement": "ACPL", "Abbott Lab.": "ABOT", "Abbott Lab (Pakistan) Ltd": "ABOT",
         "Pak Suzuki": "PSMC", "Pak Suzuki Company Ltd": "PSMC", "Mari Petroleum Company Limited": "MARI",
         "Pakistan Int'l Bulk Terminal Ltd": "PIBTL", "Shell (Pakistan) Ltd": "SHEL",
         "Shell (Pakistan) Limited": "SHEL", "International Ind. Ltd": "INIL",
         "Lotte Chemicals Ltd": "LOTCHEM", "Frieslandcampina Engro Foods Ltd": "FCEPL",
         "Orix Leasing Pakistan Limited": "OLPL", "Sui Northern Gas": "SNGP",
         "K-Electric Limited": "KEL", "BankIslami Pakistan Limited": "BIPL", "Treet Corporation": "TREET",
         "Treet Corporation Ltd": "TREET", "Treet Corporation Limited": "TREET"}
ch = pd.read_csv("data/raw/notices/index_changes.csv", dtype={"doc_id": str})
ch["announced_at"] = pd.to_datetime(ch["announced_at"]); ch["effective_date"] = pd.to_datetime(ch["effective_date"], errors="coerce")
from mbf.adjust import DEBT_RE
syms = set(pd.read_parquet("data/research/features.parquet", columns=["symbol"]).symbol.unique())
idx = {k: v for k, v in rights.name_index().items() if v in syms}
def sym(r):
    if isinstance(r.symbol_in_text, str) and r.symbol_in_text.strip() in syms:
        return r.symbol_in_text.strip()
    if r.company in ALIAS: return ALIAS[r.company]
    return rights.match_symbol(r.company, idx, cutoff=0.85)
ch["symbol"] = [sym(r) for r in ch.itertuples()]
print("matched:", ch.symbol.notna().mean().round(3), "of", len(ch))
um = ch[ch.symbol.isna()].company.drop_duplicates()
print("UNMATCHED:", len(um)); print(um.to_string())
ch.to_csv("data/research/index_changes_mapped.csv", index=False)
if "--names" in sys.argv: sys.exit()

cols = ["symbol","date","adj_open","adj_close","traded","factor","in_universe","to_rank"]
f = pd.read_parquet("data/research/features.parquet", columns=cols)
P = es._panel(f); s, pos, w = P
ev = ch.dropna(subset=["symbol"]).copy()
# information usable from the close of the first session strictly after the notice's DATE
# (notices are posted 12:00-21:00; many after the close)
ev["a1"] = s.searchsorted(ev["announced_at"].dt.normalize() + pd.Timedelta(days=1))
ev["eff"] = s.searchsorted(ev["effective_date"])            # first session on/after w.e.f. date
ev = ev[(ev.a1 < len(s)) & ev.effective_date.notna() & (ev.eff < len(s))]
ev = ev[ev.announced_at >= "2013-11-04"]
ev = ev.drop_duplicates(["index", "symbol", "direction", "effective_date"])
print(ev.groupby(["index","direction"]).size())
print("sessions announcement->effective:", (ev.eff - ev.a1).describe().round(1).to_dict())
res = []
def run(name, e, a, b, entry="close", exit="open"):
    e = e.copy(); e["entry_idx"], e["exit_idx"] = a, b
    e = e[(e.entry_idx >= 0) & (e.exit_idx > e.entry_idx)]
    t = es.trades(f, e[["symbol","entry_idx","exit_idx"]], entry=entry, exit=exit, panel=P)
    res.append(es.summarize(t, name)); return t
for ix in ["KSE100", "KSE30", "KMI30", "ALL"]:
    for d in ["in", "out"]:
        e = ev[(ev.direction == d) & ((ev["index"] == ix) | (ix == "ALL"))]
        tag = f"{ix} {d}"
        run(f"{tag}: ann close d+1 -> close eff-1", e, e.a1, e.eff - 1, "close", "close")
        run(f"{tag}: ann close d+1 -> open d+6", e, e.a1, e.a1 + 5, "close", "open")
        run(f"{tag}: close eff-6 -> close eff-1", e, e.eff - 6, e.eff - 1, "close", "close")
        run(f"{tag}: close eff-1 -> open eff+5 (after)", e, e.eff - 1, e.eff + 5, "close", "open")
        run(f"{tag}: close eff -> open eff+5", e, e.eff, e.eff + 5, "close", "open")
out = pd.DataFrame(res)
for c in ["win","mean_net","edge","dev_edge","hold_net","hold_edge"]: out[c] = (out[c]*100).round(2)
for c in ["t","dev_t","hold_t","nights"]: out[c] = out[c].round(1)
print(out[["signal","n","nights","win","mean_net","edge","t","yrs+","dev_edge","dev_t","hold_n","hold_edge","hold_t"]].to_string(index=False))
out.to_csv("data/research/index_results.csv", index=False)
