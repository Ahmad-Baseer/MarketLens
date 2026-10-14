"""NCCPL foreign (FIPI) and local (LIPI) investor flows, by sector.

NCCPL publishes net buying/selling per client type and sector. History was
collected from nccpl.com.pk in the user's own browser (the site is behind a
Cloudflare check that blocks scripts): daily 2015-12-09..2016-12-28, then
Monday-Friday weekly ranges (a range query returns the exact sum of its days —
verified against the daily data). Only the ready market (REG) is kept.

A sector-week's flow is a client group's net value divided by the sector's
traded value that week (sum of all buy values = turnover), so sectors of
different size compare.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from mbf import store

FIPI = {"FOREIGN INDIVIDUAL", "FOREIGN CORPORATES", "OVERSEAS PAKISTANI"}
GROUPS = {"INDIVIDUALS": "individuals", "COMPANIES": "companies", "BANKS / DFI": "banks",
          "NBFC": "nbfc", "MUTUAL FUNDS": "mutual_funds", "OTHER ORGANIZATION": "other_org",
          "BROKER PROPRIETARY TRADING": "broker_prop", "INSURANCE COMPANIES": "insurance"}


def load_export(path: str | Path) -> pd.DataFrame:
    """The browser export: {key: {rows: [[client, sec, buy, sell, net, bvol, svol], ...]}}.
    Keys: '<kind>|YYYY-MM-DD' (one day) or 'W|<kind>|YYYY-MM-DD' (Mon-Fri week)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    recs = []
    for key, v in raw.items():
        if key.startswith("__") or not isinstance(v, dict):
            continue
        parts = key.split("|")
        freq, kind, start = ("W", parts[1], parts[2]) if parts[0] == "W" else ("D", parts[0], parts[1])
        for c, sec, buy, sell, net, bv, sv in v.get("rows", []):
            recs.append((freq, kind.split("-")[0], start, c.strip(), sec, buy, -abs(sell), net))
    df = pd.DataFrame(recs, columns=["freq", "kind", "start", "client", "sec", "buy", "sell", "net"])
    df["start"] = pd.to_datetime(df["start"])
    sectors = raw.get("__sectors", {})
    df["sector"] = df["sec"].map(sectors)
    return df[df["client"] != ""]


def weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Sector x week panel (week = Monday). Daily rows are summed into their week;
    weeks that exist as weekly ranges take precedence."""
    d = df[df["freq"] == "D"].copy()
    d["week"] = d["start"] - pd.to_timedelta(d["start"].dt.weekday, unit="D")
    w = df[df["freq"] == "W"].copy()
    w["week"] = w["start"]
    d = d[~d["week"].isin(set(w["week"]))]
    x = pd.concat([d, w], ignore_index=True)
    x["group"] = np.where(x["client"].isin(FIPI), "foreign", x["client"].map(GROUPS))
    x = x.dropna(subset=["group"])
    g = x.groupby(["week", "sec", "group"], as_index=False)[["buy", "sell", "net"]].sum()
    net = g.pivot_table(index=["week", "sec"], columns="group", values="net", aggfunc="sum").fillna(0)
    turnover = g.groupby(["week", "sec"])["buy"].sum()
    out = net.div(turnover, axis=0).add_suffix("_flow")
    out["turnover"] = turnover
    out["foreign_net"] = net.get("foreign", 0.0)
    out["check"] = net.sum(axis=1) / turnover          # FIPI + LIPI net should be ~0
    return out.reset_index()


def psx_sector(name: str) -> str:
    return re.sub(r"\s+", " ", name.upper().replace(" AND ", " & ")).strip()
