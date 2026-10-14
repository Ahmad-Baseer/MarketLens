"""HTTP client for the PSX Data Portal (dps.psx.com.pk).

The portal is public, but its data endpoints only answer requests that carry
the header ``X-Req-Id`` with a key the homepage embeds as
``window.__ps = {"_k": "..."}``. Without it they return 404 (plain request) or
403 (XHR without key). We read the key exactly as the site's own JavaScript
does and refresh it whenever a request comes back 403.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date

import httpx

from mbf import config

log = logging.getLogger(__name__)

_KEY_RE = re.compile(r'"_k"\s*:\s*"([^"]+)"')


class PSXError(RuntimeError):
    pass


class PSXClient:
    def __init__(self, base: str = config.PSX_BASE, user_agent: str = config.USER_AGENT,
                 min_interval: float = config.REQUEST_INTERVAL, timeout: float = 60.0,
                 retries: int = 4):
        self._http = httpx.Client(base_url=base, timeout=timeout, follow_redirects=True,
                                  headers={"User-Agent": user_agent})
        self._min_interval = min_interval
        self._retries = retries
        self._key: str | None = None
        self._last = 0.0
        self.requests = 0

    # ------------------------------------------------------------ plumbing
    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _throttle(self):
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def refresh_key(self) -> str:
        self._throttle()
        r = self._http.get("/")
        r.raise_for_status()
        m = _KEY_RE.search(r.text)
        if not m:
            raise PSXError("request key (window.__ps._k) not found on PSX homepage — "
                           "the site has changed and the client needs updating")
        self._key = m.group(1)
        return self._key

    def _request(self, method: str, path: str, data: dict | None = None) -> httpx.Response:
        if self._key is None:
            self.refresh_key()
        last_err: Exception | None = None
        for attempt in range(self._retries + 1):
            self._throttle()
            headers = {"X-Req-Id": self._key or "", "X-Requested-With": "XMLHttpRequest",
                       "Referer": config.PSX_BASE + "/", "Accept": "*/*"}
            try:
                r = self._http.request(method, path, data=data, headers=headers)
                self.requests += 1
            except httpx.TransportError as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 403 and attempt < self._retries:
                log.info("403 on %s — refreshing request key", path)
                self.refresh_key()
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self._retries:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise PSXError(f"{method} {path} -> HTTP {r.status_code}")
            return r
        raise PSXError(f"{method} {path} failed after {self._retries + 1} attempts: {last_err}")

    def download(self, path: str) -> bytes:
        """A PSX document (notice/announcement PDF), throttled like every other call."""
        for attempt in range(self._retries + 1):
            self._throttle()
            try:
                r = self._http.get(path, headers={"Referer": config.PSX_BASE + "/"})
                self.requests += 1
            except httpx.TransportError:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self._retries:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise PSXError(f"GET {path} -> HTTP {r.status_code}")
            return r.content
        raise PSXError(f"GET {path} failed after {self._retries + 1} attempts")

    # ------------------------------------------------------------ endpoints
    def historical(self, d: date) -> str:
        """All symbols' OHLCV + LDCP for one trading day (HTML)."""
        return self._request("POST", "/historical", {"date": d.isoformat()}).text

    def eod(self, symbol: str) -> list[list]:
        """~5 years of [unix_ts, close, volume, open] for a symbol or index."""
        j = self._request("GET", f"/timeseries/eod/{symbol}").json()
        if not j.get("status"):
            raise PSXError(f"eod {symbol}: {j.get('message')}")
        return j.get("data") or []

    def symbols(self) -> list[dict]:
        return self._request("GET", "/symbols").json()

    def market_watch(self) -> str:
        return self._request("GET", "/market-watch").text

    def company(self, symbol: str) -> str:
        return self._request("GET", f"/company/{symbol}").text

    def company_reports(self, symbol: str) -> str:
        return self._request("GET", f"/company/reports/{symbol}").text

    def payouts(self, symbol: str = "", count: int = 50, offset: int = 0) -> str:
        return self._request("POST", "/payouts",
                             {"symbol": symbol, "count": count, "offset": offset}).text

    def announcements(self, date_from: date | None = None, date_to: date | None = None,
                      symbol: str = "", ann_type: str = "C", count: int = 50,
                      offset: int = 0) -> str:
        data = {"type": ann_type, "symbol": symbol, "query": "", "count": count,
                "offset": offset, "page": "annc",
                "date_from": date_from.isoformat() if date_from else "",
                "date_to": date_to.isoformat() if date_to else ""}
        return self._request("POST", "/announcements", data).text
