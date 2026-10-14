"""Entry/exit timing: PSX's average liquid stock gains ~+0.28% overnight (close
-> next open) and loses ~-0.20% during the session (open -> close), in every
year 2014-2026. So *when* a signal is traded matters as much as *what*.

Variants (h = holding period in sessions), for signal day t:
  eo_xc  enter next open (t+1),  exit close of t+h       (the default rules)
  eo_xo  enter next open (t+1),  exit open of t+1+h
  ec_xo  enter close of t,       exit open of t+h        (needs a pre-close signal)
  ec1_xo enter close of t+1,     exit open of t+1+h      (publish after close, buy
                                                          near the next close)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mbf.research.outcomes import DEFAULT_COST

VARIANTS = ("eo_xc", "eo_xo", "ec_xo", "ec1_xo")


def returns(f: pd.DataFrame, variant: str, h: int, cost: float = DEFAULT_COST) -> pd.Series:
    """Net return per row (NaN where the trade can't happen). f sorted by symbol, date."""
    g = f.groupby("symbol", sort=False)

    def at(col, k):
        return g[col].shift(-k) if k else f[col]

    def tr(k):
        return (g["traded"].shift(-k) if k else f["traded"]).fillna(False).astype(bool)

    if variant == "eo_xc":
        ent, ok_e, ext, ok_x = at("adj_open", 1), tr(1) & ~at("locked_up", 1).fillna(False).astype(bool), at("adj_close", h), tr(h)
    elif variant == "eo_xo":
        ent, ok_e, ext, ok_x = at("adj_open", 1), tr(1) & ~at("locked_up", 1).fillna(False).astype(bool), at("adj_open", 1 + h), tr(1 + h)
    elif variant == "ec_xo":
        ent, ok_e, ext, ok_x = at("adj_close", 0), tr(0) & ~f["locked_up"], at("adj_open", h), tr(h)
    elif variant == "ec1_xo":
        ent, ok_e, ext, ok_x = at("adj_close", 1), tr(1) & ~at("locked_up", 1).fillna(False).astype(bool), at("adj_open", 1 + h), tr(1 + h)
    else:
        raise ValueError(variant)
    r = ext / ent - 1 - cost
    return r.where(ok_e & ok_x)
