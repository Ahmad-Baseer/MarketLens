"""Do NCCPL sector flows predict next week's returns? Usage: flows_study.py EXPORT.json"""
import sys; sys.path.insert(0, "backend")
import pandas as pd, numpy as np
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
from mbf.research import eventstudy as es, flows
df = flows.load_export(sys.argv[1])
print(df.groupby(["freq","kind"]).start.agg(["min","max","nunique"]))
W = flows.weekly(df)
print("weeks:", W.week.nunique(), W.week.min().date(), W.week.max().date(), "| FIPI+LIPI check |max|:", W.check.abs().max().round(4))
sec = df.dropna(subset=["sector"]).drop_duplicates("sec").set_index("sec").sector
W["sector"] = W.sec.map(sec)
print(W.groupby("sector").week.nunique().sort_values().to_string())
W = W[W.sector.notna() & (W.sector != "All other Sectors") & ~W.sec.isin([" ", "---"])]

cols = ["symbol","date","adj_open","adj_close","traded","factor","in_universe","to_rank"]
f = pd.read_parquet("data/research/features.parquet", columns=cols)
P = es._panel(f); s, pos, w = P
U = w["in_universe"].fillna(False)
sy = pd.read_parquet("data/ref/symbols.parquet")
sy["psx_sector"] = sy.sector.fillna("")
W["psx_sector"] = W.sector.map(flows.psx_sector)
print("sectors mapped:", sorted(set(W.psx_sector) & set(sy.psx_sector)), "unmapped:", sorted(set(W.psx_sector) - set(sy.psx_sector)))
members = sy.groupby("psx_sector").symbol.apply(list).to_dict()

# timing: week w (Mon..Fri) known by Monday evening at the latest -> enter at the close of the
# first session of w+1, exit at the opening auction 5 sessions later
W["a"] = s.searchsorted(W.week + pd.Timedelta(days=7))
W = W[W.a + 5 < len(s)]
# trailing z-score of each flow per sector (26 weeks, known at the time)
for c in ["foreign_flow", "mutual_funds_flow", "individuals_flow", "companies_flow", "insurance_flow", "banks_flow", "broker_prop_flow"]:
    if c not in W: continue
    W = W.sort_values(["sec", "week"])
    g = W.groupby("sec")[c]
    W[c + "_z"] = (W[c] - g.transform(lambda x: x.shift(1).rolling(26, min_periods=12).mean())) / g.transform(lambda x: x.shift(1).rolling(26, min_periods=12).std())

def trades_for(sel, name):
    rows = []
    for r in sel.itertuples():
        for sym in members.get(r.psx_sector, []):
            if sym in U.columns and bool(U.iat[int(r.a), U.columns.get_loc(sym)]):
                rows.append((sym, int(r.a), int(r.a) + 5))
    e = pd.DataFrame(rows, columns=["symbol","entry_idx","exit_idx"])
    t = es.trades(f, e, entry="close", exit="open", panel=P)
    return es.summarize(t, name)

res = []
for col in ["foreign_flow", "mutual_funds_flow", "individuals_flow", "insurance_flow", "companies_flow", "broker_prop_flow"]:
    if col not in W: continue
    rk = W.groupby("week")[col].rank(ascending=False, method="first")
    n = W.groupby("week")[col].transform("count")
    res.append(trades_for(W[rk <= 1], f"{col}: top-1 sector"))
    res.append(trades_for(W[rk <= 2], f"{col}: top-2 sectors"))
    res.append(trades_for(W[rk > n - 2], f"{col}: bottom-2 sectors"))
    z = col + "_z"
    res.append(trades_for(W[W[z] > 2], f"{col}: z > 2 (unusual buying)"))
    res.append(trades_for(W[W[z] < -2], f"{col}: z < -2 (unusual selling)"))
out = pd.DataFrame(res)
for c in ["win","mean_net","edge","dev_edge","hold_net","hold_edge"]: out[c] = (out[c]*100).round(2)
for c in ["t","dev_t","hold_t","nights"]: out[c] = out[c].round(1)
print(out[["signal","n","win","mean_net","edge","t","yrs+","dev_edge","dev_t","hold_n","hold_edge","hold_t"]].to_string(index=False))
out.to_csv("data/research/flows_results.csv", index=False)

# market level: total foreign net / market turnover in week w vs the market's next 5 sessions
M = W.groupby("week").agg(fnet=("foreign_net","sum"), to=("turnover","sum"), a=("a","first")).reset_index()
mp = pd.read_parquet("data/indices/market_proxy.parquet")
lvl = mp.set_index("date")["level_cw"].reindex(s)
M["ff"] = M.fnet / M.to
M["next"] = [lvl.iloc[a + 5] / lvl.iloc[a] - 1 if a + 5 < len(s) else np.nan for a in M.a]
M["same"] = [lvl.iloc[a - 1] / lvl.iloc[max(a - 6, 0)] - 1 for a in M.a]
M = M.dropna()
for lab, col in [("next week", "next"), ("same week (not tradeable)", "same")]:
    c = np.corrcoef(M.ff, M[col])[0, 1]
    q = pd.qcut(M.ff, 5, labels=False)
    print(f"market {lab}: corr {c:+.3f} (t~{c*np.sqrt(len(M)-2)/np.sqrt(1-c*c):+.1f}, n={len(M)}); mean return by foreign-flow quintile:",
          (M.groupby(q)[col].mean() * 100).round(2).tolist())
