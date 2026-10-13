"""Symbols, sectors, index membership and index levels."""
from __future__ import annotations

import logging

import pandas as pd

from mbf import config, store
from mbf.psx.client import PSXClient, PSXError
from mbf.psx.parsers import eod_to_frame, parse_market_watch

log = logging.getLogger(__name__)


def update_symbols(client: PSXClient) -> pd.DataFrame:
    df = pd.DataFrame(client.symbols())
    df = df.rename(columns={"sectorName": "sector", "isETF": "is_etf", "isDebt": "is_debt"})
    df["is_future"] = df["symbol"].str.contains("-", regex=False)
    df["fetched_at"] = pd.Timestamp.now(tz=config.TZ).tz_localize(None)
    store.write_parquet(df, store.path("ref", "symbols.parquet"))
    log.info("symbols: %d total, %d equities", len(df), int(equity_mask(df).sum()))
    return df


def equity_mask(sym: pd.DataFrame) -> pd.Series:
    return ~sym["is_debt"].astype(bool) & ~sym["is_etf"].astype(bool) & ~sym["is_future"]


def equity_symbols() -> list[str]:
    sym = store.read_parquet(store.path("ref", "symbols.parquet"))
    if sym.empty:
        raise FileNotFoundError("ref/symbols.parquet missing — run `mbf ref` first")
    return sorted(sym.loc[equity_mask(sym), "symbol"].tolist())


def update_market_watch(client: PSXClient) -> pd.DataFrame:
    mw = parse_market_watch(client.market_watch())
    mw["fetched_at"] = pd.Timestamp.now(tz=config.TZ).tz_localize(None)
    store.write_parquet(mw, store.path("ref", "market_watch.parquet"))
    sym = store.read_parquet(store.path("ref", "symbols.parquet"))
    if not sym.empty:
        codes = (mw.merge(sym[["symbol", "sector"]], on="symbol", how="inner")
                   .query("sector != ''")
                   .groupby("sector_code")["sector"].agg(lambda s: s.mode().iat[0])
                   .rename("sector").reset_index())
        store.write_parquet(codes, store.path("ref", "sector_codes.parquet"))
    log.info("market watch: %d symbols", len(mw))
    return mw


def update_indices(client: PSXClient, indices: list[str] | None = None) -> pd.DataFrame:
    """PSX only serves ~5 years per index, so we merge into what we already
    hold: the history deepens every day this runs."""
    frames = []
    for code in indices or config.INDICES:
        try:
            frames.append(eod_to_frame(client.eod(code), code))
        except PSXError as e:
            log.warning("index %s: %s", code, e)
    p = store.path("indices", "eod.parquet")
    old = store.read_parquet(p)
    df = pd.concat([old, *frames], ignore_index=True) if frames else old
    df = (df.sort_values(["symbol", "date"])
            .drop_duplicates(["symbol", "date"], keep="last").reset_index(drop=True))
    store.write_parquet(df, p)
    log.info("indices: %d rows across %s", len(df), ", ".join(sorted(df["symbol"].unique())))
    return df
