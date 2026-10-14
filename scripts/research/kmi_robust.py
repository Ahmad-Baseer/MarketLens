import sys; sys.path.insert(0, "backend")
import pandas as pd, numpy as np
pd.set_option("display.width", 250)
from mbf.research import eventstudy as es
cols = ["symbol","date","adj_open","adj_close","traded","factor","in_universe","to_rank"]
f = pd.read_parquet("data/research/features.parquet", columns=cols)
P = es._panel(f); s, pos, w = P
U = w["in_universe"].fillna(False)
ch = pd.read_csv("data/research/index_changes_mapped.csv", parse_dates=["announced_at","effective_date"])
ev = ch[(ch["index"] == "KMI30")].dropna(subset=["symbol"]).copy()
ev["a1"] = s.searchsorted(ev["announced_at"].dt.normalize() + pd.Timedelta(days=1))
ev["eff"] = s.searchsorted(ev["effective_date"])
ev = ev[(ev.announced_at >= "2013-11-04") & ev.effective_date.notna()].drop_duplicates(["symbol","direction","effective_date"])
ev["hour"] = ev.announced_at.dt.hour
print("announce hour:", ev.hour.value_counts().sort_index().to_dict())
res = []; T = {}
def run(name, e, a, b, entry="close", exit="open"):
    e = e.copy(); e["entry_idx"], e["exit_idx"] = np.asarray(a), np.asarray(b)
    e = e[(e.entry_idx >= 0) & (e.exit_idx > e.entry_idx) & (e.exit_idx < len(s))]
    t = es.trades(f, e[["symbol","entry_idx","exit_idx","doc_id"]], entry=entry, exit=exit, panel=P)
    res.append(es.summarize(t, name)); T[name] = t; return t
I = ev[ev.direction == "in"]
run("in: close d+1 -> open d+6 (base)", I, I.a1, I.a1 + 5)
run("in: close d+1 -> open d+4", I, I.a1, I.a1 + 3)
run("in: close d+1 -> open d+2", I, I.a1, I.a1 + 1)
run("in: close d+2 -> open d+7 (1 day late)", I, I.a1 + 1, I.a1 + 6)
run("in: close d+3 -> open d+8 (2 days late)", I, I.a1 + 2, I.a1 + 7)
run("in: close d+1 -> open eff", I, I.a1, I.eff)
run("in: close d+1 -> close eff", I, I.a1, I.eff, "close", "close")
run("in: close d+1 -> open d+11", I, I.a1, I.a1 + 10)
run("in: same-day close d0 -> open d+6 (if notice before close)", I[I.hour < 15], I[I.hour < 15].a1 - 1, I[I.hour < 15].a1 + 5)
uni = np.array([bool(U.iat[int(i), U.columns.get_loc(sy)]) if sy in U.columns else False for sy, i in zip(I.symbol, I.a1)])
run("in: base, universe stocks only", I[uni], I[uni].a1, I[uni].a1 + 5)
run("in: base, not in universe", I[~uni], I[~uni].a1, I[~uni].a1 + 5)
O = ev[ev.direction == "out"]
run("out: close d+1 -> open d+6", O, O.a1, O.a1 + 5)
out = pd.DataFrame(res)
for c in ["win","mean_net","edge","dev_edge","hold_net","hold_edge"]: out[c] = (out[c]*100).round(2)
for c in ["t","dev_t","hold_t","nights"]: out[c] = out[c].round(1)
print(out[["signal","n","nights","win","mean_net","edge","t","yrs+","dev_edge","dev_t","hold_n","hold_net","hold_edge","hold_t"]].to_string(index=False))
t = T["in: close d+1 -> open d+6 (base)"]
g = t.groupby("date").agg(n=("net","size"), net=("net","mean"), ctrl=("ctrl","mean"), edge=("diff","mean"))
g[["net","ctrl","edge"]] = (g[["net","ctrl","edge"]]*100).round(2)
print(g.to_string())
print("median net %.2f%%, worst %.2f%%, best %.2f%%" % (t.net.median()*100, t.net.min()*100, t.net.max()*100))
