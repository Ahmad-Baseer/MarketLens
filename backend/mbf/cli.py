"""Command line entry point:  python -m mbf <command>

One-time setup (in this order):
    mbf backfill-prices        ~1.5 h  daily prices 2000 -> today
    mbf seed-akd               ~1 min  import legacy AKD files
    mbf ref                    ~10 s   symbols, sectors, index levels
    mbf company-sweep          ~30 min fundamentals snapshot + report list
    mbf events --since 2024-01-01      payouts + announcements
    mbf adjust                 ~1 min  corporate-action adjustment + market proxy
    mbf quality                        data-quality report -> reports/

Every evening after the close:
    mbf update
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta


def _setup_logging(verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _client():
    from mbf.psx.client import PSXClient
    return PSXClient()


def cmd_backfill_prices(a):
    from mbf import config
    from mbf.ingest import prices
    start = date.fromisoformat(a.start) if a.start else config.HISTORY_START
    end = date.fromisoformat(a.end) if a.end else prices.last_closed_session()
    with _client() as c:
        res = prices.backfill(c, start, end)
    logging.info("backfill done: %s", res)
    prices.compact()


def cmd_recheck_holidays(a):
    from mbf.ingest import prices
    with _client() as c:
        rec = prices.recheck_holidays(c, date.fromisoformat(a.since) if a.since else None)
    logging.info("recheck done: %d recovered %s", len(rec), [str(d) for d in rec])
    if rec:
        prices.compact()


def cmd_compact(a):
    from mbf.ingest import prices
    prices.compact()


def cmd_adjust(a):
    from mbf import adjust, market
    daily, _ = adjust.run()
    market.build(daily)


def cmd_seed_akd(a):
    from mbf.ingest import akd_seed
    akd_seed.run()


def cmd_ref(a):
    from mbf.ingest import reference
    with _client() as c:
        reference.update_symbols(c)
        reference.update_market_watch(c)
        reference.update_indices(c)


def cmd_company_sweep(a):
    from mbf.ingest import company, reference
    syms = a.symbols.split(",") if a.symbols else reference.equity_symbols()
    with _client() as c:
        res = company.sweep(c, syms, with_reports=not a.no_reports)
    if res["failed"]:
        logging.warning("company sweep: %d failed: %s", len(res["failed"]), ",".join(res["failed"][:30]))


def cmd_events(a):
    from mbf.ingest import events, prices
    since = date.fromisoformat(a.since) if a.since else date.today() - timedelta(days=7)
    with _client() as c:
        events.update_payouts(c)
        events.update_announcements(c, since, prices.last_closed_session())


def cmd_quality(a):
    from mbf import quality
    path = quality.run()
    logging.info("quality report: %s", path)


def cmd_update(a):
    """The evening job: everything incremental, in dependency order."""
    from mbf import adjust, market
    from mbf.ingest import company, events, prices, reference
    with _client() as c:
        res = prices.update(c)
        logging.info("prices: %s", res)
        prices.compact()
        daily, _ = adjust.run()
        market.build(daily)
        reference.update_symbols(c)
        reference.update_market_watch(c)
        reference.update_indices(c)
        events.update_payouts(c)
        last = prices.last_closed_session()
        ann = events.update_announcements(c, last - timedelta(days=5), last)
        # refresh fundamentals for companies that just filed results
        recent = ann[(ann["announced_at"] >= str(last - timedelta(days=5)))
                     & ann["title"].str.contains("financial result", case=False, na=False)]
        syms = sorted(set(recent["symbol"]) & set(reference.equity_symbols()))
        if a.full_sweep:
            syms = reference.equity_symbols()
        if syms:
            company.sweep(c, syms, with_reports=True)
        logging.info("update done: %d PSX requests", c.requests)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mbf", description="PSX signal provider — data pipeline",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("backfill-prices", help="download daily prices for a date range")
    p.add_argument("--start", help="YYYY-MM-DD (default 2000-01-01)")
    p.add_argument("--end", help="YYYY-MM-DD (default last closed session)")
    p.set_defaults(fn=cmd_backfill_prices)

    p = sub.add_parser("recheck-holidays", help="re-request days marked as holidays")
    p.add_argument("--since", help="YYYY-MM-DD (default: all)")
    p.set_defaults(fn=cmd_recheck_holidays)

    sub.add_parser("compact", help="merge daily price files into one table").set_defaults(fn=cmd_compact)
    sub.add_parser("adjust", help="corporate-action adjustment from LDCP").set_defaults(fn=cmd_adjust)
    sub.add_parser("seed-akd", help="one-time import of legacy AKD files").set_defaults(fn=cmd_seed_akd)
    sub.add_parser("ref", help="symbols, sectors, index levels").set_defaults(fn=cmd_ref)

    p = sub.add_parser("company-sweep", help="fundamentals snapshot for all (or given) companies")
    p.add_argument("--symbols", help="comma-separated; default all equities")
    p.add_argument("--no-reports", action="store_true", help="skip the report-PDF listing")
    p.set_defaults(fn=cmd_company_sweep)

    p = sub.add_parser("events", help="payouts + announcements")
    p.add_argument("--since", help="YYYY-MM-DD for announcements (default: last 7 days)")
    p.set_defaults(fn=cmd_events)

    sub.add_parser("quality", help="write the data-quality report").set_defaults(fn=cmd_quality)

    p = sub.add_parser("update", help="daily incremental update (run after the close)")
    p.add_argument("--full-sweep", action="store_true", help="refresh fundamentals for every company")
    p.set_defaults(fn=cmd_update)

    a = ap.parse_args(argv)
    _setup_logging(a.verbose)
    a.fn(a)


if __name__ == "__main__":
    main()
