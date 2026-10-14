import sys; sys.path.insert(0, "backend")
import pandas as pd, numpy as np
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
from mbf.research import eventstudy as es
cols = ["symbol","date","adj_open","adj_close","traded","factor","in_universe","to_rank"]
f = pd.read_parquet("data/research/features.parquet", columns=cols)
P = es._panel(f)
s, pos, w = P
U = w["in_universe"].fillna(False)
ev = pd.read_parquet("data/research/rights_events.parquet")
ev["x_idx"] = ev["x_idx"].astype(int)
def univ(e, idx_col):
    return np.array([bool(U.iat[int(i), U.columns.get_loc(sy)]) if sy in U.columns and 0 <= int(i) < len(s) else False
                     for sy, i in zip(e.symbol, e[idx_col])])
res = []
def run(name, e, a_col, b_col, entry="close", exit="open", only_univ=False):
    e = e.dropna(subset=[a_col, b_col]).copy()
    e["entry_idx"], e["exit_idx"] = e[a_col].astype(int), e[b_col].astype(int)
    if only_univ:
        e = e[univ(e, "entry_idx")]
    t = es.trades(f, e[["symbol","entry_idx","exit_idx"]], entry=entry, exit=exit, panel=P)
    r = es.summarize(t, name); res.append(r); return t
X = ev.copy()
for k in (5, 10):
    X[f"xm{k}"] = X.x_idx - k
X["xm1"] = X.x_idx - 1
for k in (1, 3, 5, 10):
    X[f"xp{k}"] = X.x_idx + k
for u in (False, True):
    tag = " [universe]" if u else ""
    run("run-up: close x-6 -> close x-1 (sell cum-rights)" + tag, X.assign(a=X.x_idx-6), "a", "xm1", "close", "close", u)
    run("run-up: close x-11 -> close x-1" + tag, X.assign(a=X.x_idx-11), "a", "xm1", "close", "close", u)
    run("ex-day: close x-1 -> close x (adjusted)" + tag, X, "xm1", "x_idx", "close", "close", u)
    run("ex-day: close x-1 -> open x (adjusted)" + tag, X, "xm1", "x_idx", "close", "open", u)
    for k in (1, 3, 5, 10):
        run(f"after ex: close x -> open x+{k}" + tag, X, "x_idx", f"xp{k}", "close", "open", u)
A = ev.dropna(subset=["ann_idx"]).copy()
A["ann_idx"] = A.ann_idx.astype(int)
A["a1"] = A.ann_idx + 1
A = A[A.a1 < A.x_idx - 1]
for u in (False, True):
    tag = " [universe]" if u else ""
    run("announcement reaction: close d-2 -> close d+1 (not tradeable)" + tag, A.assign(a=A.ann_idx-2), "a", "a1", "close", "close", u)
    for k in (3, 5):
        run(f"after announcement: close d+1 -> open d+{1+k}" + tag, A.assign(b=A.a1+k), "a1", "b", "close", "open", u)
    run("announcement -> ex: close d+1 -> close x-1" + tag, A.assign(b=A.x_idx-1), "a1", "b", "close", "close", u)
out = pd.DataFrame(res)
for c in ["win","mean_net","edge","dev_edge","hold_net","hold_edge"]:
    out[c] = (out[c]*100).round(2)
for c in ["t","dev_t","hold_t","nights"]:
    out[c] = out[c].round(1)
print(out[["signal","n","nights","win","mean_net","edge","t","yrs+","dev_edge","dev_t","hold_n","hold_edge","hold_t"]].to_string(index=False))
out.to_csv("data/research/rights_results.csv", index=False)
