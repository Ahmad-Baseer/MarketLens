import sys; sys.path.insert(0, "backend")
import pandas as pd, numpy as np
pd.set_option("display.width", 250)
from mbf.research import eventstudy as es, flows
df = flows.load_export(sys.argv[1])
W = flows.weekly(df)
ok = np.isfinite(W.check)
print("check (FIPI+LIPI net / turnover): median %.2e, 99th pct |x| %.2e, non-finite rows %d" % (W.check[ok].median(), W.check[ok].abs().quantile(.99), (~ok).sum()))
tot = W.groupby("week").agg(fnet=("foreign_net", "sum"), to=("turnover", "sum"))
print("weekly foreign net (Rs bn): mean %.2f, sd %.2f; market turnover (Rs bn/wk) median %.1f" % (tot.fnet.mean()/1e9, tot.fnet.std()/1e9, tot.to.median()/1e9))
print("by year foreign net (Rs bn):", (tot.fnet.groupby(tot.index.year).sum()/1e9).round(1).to_dict())
sec = df.dropna(subset=["sector"]).drop_duplicates("sec").set_index("sec").sector
W["sector"] = W.sec.map(sec); W["psx_sector"] = W.sector.map(flows.psx_sector)
core = ["Cement","Fertilizer","Food and Personal Care Products","Oil and Gas Exploration Companies","Oil and Gas Marketing Companies","Power Generation and Distribution","Commercial Banks","Technology and Communication","Textile Composite"]
W = W[W.sector.isin(core)].sort_values(["sec","week"])
cols = ["symbol","date","adj_open","adj_close","traded","factor","in_universe","to_rank"]
f = pd.read_parquet("data/research/features.parquet", columns=cols)
P = es._panel(f); s, pos, w = P
U = w["in_universe"].fillna(False)
sy = pd.read_parquet("data/ref/symbols.parquet"); members = sy.groupby(sy.sector.fillna("")).symbol.apply(list).to_dict()
W["a"] = s.searchsorted(W.week + pd.Timedelta(days=7))
W = W[W.a + 5 < len(s)]
# 4-week cumulative foreign flow ratio
g = W.groupby("sec")
W["f4"] = g.foreign_net.transform(lambda x: x.rolling(4).sum()) / g.turnover.transform(lambda x: x.rolling(4).sum())
W["mf4"] = g.mutual_funds_flow.transform(lambda x: x.rolling(4).mean())
res = []
def trades_for(sel, name, hold=5):
    rows = []
    for r in sel.itertuples():
        for sym in members.get(r.psx_sector, []):
            if sym in U.columns and bool(U.iat[int(r.a), U.columns.get_loc(sym)]):
                rows.append((sym, int(r.a), int(r.a) + hold))
    t = es.trades(f, pd.DataFrame(rows, columns=["symbol","entry_idx","exit_idx"]), entry="close", exit="open", panel=P)
    res.append(es.summarize(t, name))
for col, lab in [("f4", "foreign 4-week"), ("mf4", "mutual funds 4-week")]:
    rk = W.groupby("week")[col].rank(ascending=False, method="first"); n = W.groupby("week")[col].transform("count")
    trades_for(W[rk <= 2], f"{lab}: top-2 sectors")
    trades_for(W[rk > n - 2], f"{lab}: bottom-2 sectors")
out = pd.DataFrame(res)
for c in ["win","mean_net","edge","dev_edge","hold_edge"]: out[c] = (out[c]*100).round(2)
for c in ["t","dev_t","hold_t"]: out[c] = out[c].round(1)
print(out[["signal","n","win","mean_net","edge","t","yrs+","dev_edge","dev_t","hold_n","hold_edge","hold_t"]].to_string(index=False))
