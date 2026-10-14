import sys, logging; sys.path.insert(0, "backend")
import pandas as pd, numpy as np
pd.set_option("display.width", 250)
from mbf.research import data, rights
f = pd.read_parquet("data/research/features.parquet", columns=["symbol", "date"])
pn = rights.psx_notices()
print(pn.groupby("kind").agg(n=("title", "size"), matched=("symbol", lambda s: s.notna().mean())))
print(pn[pn.symbol.isna()].sample(15, random_state=0)[["kind","name"]].to_string())
ev = rights.events(f)
ev.to_parquet("data/research/rights_events.parquet")
print(len(ev), ev.x_date.dt.year.value_counts().sort_index().to_dict())
print(ev.sources.value_counts())
print("with decision date:", ev.ann_idx.notna().sum())
print(ev.factor.describe())
# validation: AKD rows that also have PSX unpaid notice
both = ev[ev.sources.str.contains("akd") & ev.sources.str.contains("psx")]
print("akd+psx overlap:", len(both))
