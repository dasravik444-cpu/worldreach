"""Archived copies of a business's own website (Common Crawl), for sites that do not answer our crawler.

Many small-business sites are down for a moment, very slow, or block unknown bots and data-centre addresses.
Common Crawl is a free, open web archive made for exactly this kind of reuse: its crawler (CCBot, which honours
robots.txt) visits billions of pages every month. We look the business's domain up in the latest crawls and
hand those archived pages to the same crawler code that reads live sites, so the same rules decide whether a
page is the business's and whether an address on it is theirs. Nothing is guessed.

Polite use, as Common Crawl asks (https://commoncrawl.org/faq): one index lookup at a time with pauses, a named
User-Agent, a cap per run, and no more lookups for the run once the index answers 503 (too many requests).
The pages themselves come from data.commoncrawl.org with byte-range requests.
"""
from __future__ import annotations

import gzip
import json
import threading
import zlib
from collections import Counter
from urllib.parse import urlsplit

from ..net import Blocked, BreakerOpen, FetchError, Http, Response
from ..util import get_logger

log = get_logger("archive")

INDEX = "https://index.commoncrawl.org"
DATA = "https://data.commoncrawl.org"
PAGE_MIMES = ("text/html", "application/xhtml+xml", "text/plain", "application/xml", "text/xml")
ROOT_ALIASES = ("/index.html", "/index.htm", "/index.php", "/home")
PREFERRED = ("contact", "about", "location", "visit", "info", "hours")


def page_key(url: str) -> str:
    """'https://www.Example.com/Contact/' -> 'example.com/Contact': scheme, www and a trailing slash do not matter."""
    p = urlsplit(url if "://" in url else "http://" + url)
    host = (p.hostname or "").lower().removeprefix("www.")
    return host + p.path.rstrip("/") + (("?" + p.query) if p.query else "")


class CommonCrawl:
    def __init__(self, http: Http, *, crawls: int = 2, interval: float = 4.0, limit: int = 300, max_lookups: int = 400):
        self.http = http
        self.n_crawls, self.interval, self.limit, self.max_lookups = crawls, interval, limit, max_lookups
        self._ids: list[str] | None = None
        self._lock = threading.Lock()
        self.lookups = 0
        # The index is often slow (HTTP 504): a few timeouts in a row only pause it for ten minutes.
        http.breaker("commoncrawl", threshold=8, cooldown=600.0)
        self.stats: Counter = Counter()

    def available(self) -> bool:
        return self.lookups < self.max_lookups and not self.http.breaker("commoncrawl").is_open()

    def crawl_ids(self) -> list[str]:
        """The newest crawls (about one a month), newest first."""
        with self._lock:
            if self._ids is None:
                try:
                    r = self.http.get(f"{INDEX}/collinfo.json", service="commoncrawl", interval=self.interval, timeout=30,
                                      retries=1, browser=False)
                    self._ids = [c["id"] for c in r.json()][: self.n_crawls] if r.status == 200 else []
                except (FetchError, BreakerOpen, ValueError, KeyError, TypeError) as exc:
                    log.info("Common Crawl index list not available: %s", exc)
                    self._ids = []
            return self._ids

    def captures(self, domain: str) -> dict[str, dict]:
        """page_key -> the newest capture of each page of the domain, from the newest crawl that has the site."""
        out: dict[str, dict] = {}
        for cid in self.crawl_ids():
            with self._lock:
                if self.lookups >= self.max_lookups:
                    break
                self.lookups += 1
            try:
                r = self.http.get(f"{INDEX}/{cid}-index", params={"url": f"{domain}/*", "output": "json",
                                                                  "filter": "=status:200", "limit": str(self.limit)},
                                  service="commoncrawl", interval=self.interval, timeout=60, retries=1, browser=False,
                                  block_statuses=(429, 503))
            except Blocked as exc:
                # "Slow down": no more lookups in this run (Common Crawl may block an address that keeps asking).
                self.http.breaker("commoncrawl").trip(f"Common Crawl index said {exc}")
                self.stats["index refused (rate limit)"] += 1
                raise
            if r.status == 404:            # "No Captures found" in this crawl
                continue
            if r.status != 200:
                raise FetchError(f"Common Crawl index HTTP {r.status}")
            for line in r.text.splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                mime = str(rec.get("mime-detected") or rec.get("mime") or "").lower()
                if not rec.get("filename") or not any(mime.startswith(m) for m in PAGE_MIMES):
                    continue
                k = page_key(rec.get("url", ""))
                if k not in out or str(rec.get("timestamp", "")) > str(out[k].get("timestamp", "")):
                    out[k] = rec
            if out:
                break
        self.stats["sites found in the archive" if out else "sites not in the archive"] += 1
        return out

    def fetch(self, rec: dict) -> Response:
        """One archived page (a WARC record read with a byte-range request)."""
        off, length = int(rec["offset"]), int(rec["length"])
        r = self.http.get(f"{DATA}/{rec['filename']}", headers={"Range": f"bytes={off}-{off + length - 1}"},
                          service="commoncrawl-data", interval=0.5, timeout=60, retries=1, browser=False,
                          max_bytes=length + 4096)
        if r.status not in (200, 206):
            raise FetchError(f"Common Crawl data HTTP {r.status}")
        try:
            raw = gzip.decompress(r.content)
        except (OSError, EOFError, zlib.error) as exc:
            raise FetchError(f"unreadable archive record: {exc}") from exc
        # WARC headers, blank line, the HTTP status line and headers, blank line, the page.
        parts = raw.split(b"\r\n\r\n", 2)
        if len(parts) < 3:
            raise FetchError("unreadable archive record")
        ctype = ""
        for line in parts[1].decode("latin-1", "replace").split("\r\n")[1:]:
            name, _, value = line.partition(":")
            if name.strip().lower() == "content-type":
                ctype = value.strip()
        self.stats["pages read from the archive"] += 1
        return Response(url=rec.get("url", ""), status=200, headers={"content-type": ctype or "text/html"},
                        content=parts[2], elapsed=0.0)


class ArchivedSite:
    """Looks like our Http client to crawl_site(), but serves the business's pages from the archive."""

    def __init__(self, cc: CommonCrawl, captures: dict[str, dict], listed_url: str):
        self.cc, self.captures = cc, captures
        self.root = page_key(listed_url)
        self.pages = 0

    def _root_capture(self) -> dict | None:
        host = self.root.split("/")[0]
        for k in [self.root, host] + [host + a for a in ROOT_ALIASES]:
            if k in self.captures:
                return self.captures[k]
        # No homepage in the archive: start from its contact/about page (or any page) instead.
        keys = sorted(self.captures, key=lambda k: (not any(w in k.lower() for w in PREFERRED), len(k)))
        return self.captures[keys[0]] if keys else None

    def robots_allowed(self, url: str, user_agent: str | None = None) -> tuple[bool, float]:
        return True, 0.0           # Common Crawl's crawler honoured the site's robots.txt when it took the copy

    def robots_reason(self, url: str) -> str:
        return "ok"

    def get(self, url: str, **kw) -> Response:
        k = page_key(url)
        rec = self.captures.get(k)
        if rec is None and k in (self.root, self.root.split("/")[0]):
            rec = self._root_capture()
        if rec is None:
            return Response(url=url, status=404, headers={"content-type": "text/html"}, content=b"", elapsed=0.0)
        self.pages += 1
        return self.cc.fetch(rec)

    def post(self, url: str, **kw) -> Response:
        raise FetchError("not available in the archive")
