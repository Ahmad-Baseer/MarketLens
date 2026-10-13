"""Load (or build and cache) the research tables: features + simulated outcomes."""
from __future__ import annotations

import logging

import pandas as pd

from mbf import store
from mbf.research import evaluate, features, outcomes

log = logging.getLogger(__name__)


def load(rebuild: bool = False, cost: float = outcomes.DEFAULT_COST) -> tuple[pd.DataFrame, pd.DataFrame]:
    fp = store.path("research", "features.parquet")
    op = store.path("research", f"outcomes_c{int(round(cost * 10000))}.parquet")
    if rebuild or not fp.exists():
        f = features.build()
    else:
        f = pd.read_parquet(fp)
    f = f.sort_values(["symbol", "date"]).reset_index(drop=True)
    f = evaluate.add_buckets(f)
    stale = True
    if op.exists() and not rebuild:
        import pyarrow.parquet as pq
        have = set(pq.read_schema(op).names)
        want = {f"{r}__net" for r in outcomes.RULES}
        stale = not want <= have or pq.read_metadata(op).num_rows != len(f)
    if stale:
        log.info("simulating %d exit rules over %s rows (cost %.2f%%)", len(outcomes.RULES),
                 f"{len(f):,}", cost * 100)
        out = outcomes.outcome_panel(f, cost=cost)
        store.write_parquet(out, op)
    else:
        out = pd.read_parquet(op)
    assert (out["date"].values == f["date"].values).all() and (out["symbol"].values == f["symbol"].values).all()
    return f, out
