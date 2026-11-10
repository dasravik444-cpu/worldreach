"""More e-mail sources for the hunt: the archived pages of websites that do not answer (Common Crawl) and a web
search for an address the business published elsewhere. Only addresses tied to the business are kept.
Synthetic data only."""
from __future__ import annotations

import gzip
import json

from conftest import make_config
from helpers import FakeHttp
from test_email_hunt import FakeResolver, place, router_for

from leadgen.db import DB
from leadgen.enrich.archive import page_key
from leadgen.enrich.email_search import queries_for, tie_to_business
from leadgen.enrich.emails import MXChecker
from leadgen.enrich.search import Result
from leadgen.hunt import EmailHunt

US = {"campaign": {"country": "US", "timezone": "America/Chicago", "language": "en", "region": "us", "lead_id_prefix": "AUS"},
      "area": {"name": "Austin", "center": [30.27, -97.74], "radius_km": 3}}


def warc(url: str, html: str) -> bytes:
    record = (f"WARC/1.0\r\nWARC-Type: response\r\nWARC-Target-URI: {url}\r\n\r\n"
              f"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n{html}")
    return gzip.compress(record.encode("utf-8"))


def archive_routes(pages: dict[str, str]) -> dict:
    """Common Crawl's index and data hosts serving the given pages {url: html}."""
    lines, routes = [], {}
    for i, (url, html) in enumerate(pages.items()):
        body = warc(url, html)
        name = f"crawl-data/CC-MAIN-2026-38/segments/x/warc/part-{i}.warc.gz"
        lines.append(json.dumps({"url": url, "timestamp": "20260915101500", "status": "200", "mime": "text/html",
                                 "filename": name, "offset": "0", "length": str(len(body))}))
        routes[f"https://data.commoncrawl.org/{name}"] = (206, body, "application/octet-stream")
    routes["https://index.commoncrawl.org/collinfo.json"] = (200, json.dumps([{"id": "CC-MAIN-2026-38"},
                                                                              {"id": "CC-MAIN-2026-33"}]), "application/json")
    routes["https://index.commoncrawl.org/CC-MAIN-2026-38-index"] = (200, "\n".join(lines), "text/plain")
    return routes


def test_page_keys_ignore_scheme_www_and_a_trailing_slash():
    assert page_key("https://www.Joes-Diner.com/Contact/") == page_key("http://joes-diner.com/Contact") == "joes-diner.com/Contact"
    assert page_key("https://joes-diner.com/") == "joes-diner.com"


def test_unreachable_website_is_read_from_its_archived_pages(tmp_path):
    db = DB(str(tmp_path / "a.sqlite"))
    with db.tx():
        place(db, "k1", "Leaf Cafe", website="https://leafcafe.in/")          # the live site answers 404 everywhere
        db.add_contact("k1", "phone", "+919830011111", source="overture", confidence="medium")
    sites = archive_routes({
        "https://www.leafcafe.in/": '<html><head><title>Leaf Cafe</title></head><body>Call 98300 11111 '
                                    '<a href="/contact">Contact</a></body></html>',
        "https://www.leafcafe.in/contact": "<html><head><title>Contact</title></head><body>Write to hello@leafcafe.in"
                                           "</body></html>",
    })
    hunt = EmailHunt(make_config(), db, limit=10, use_sheets=False, http=FakeHttp(router_for(sites)),
                     resolver=FakeResolver(set()), mx=MXChecker(enabled=False), workers=1)
    code, s = hunt.run()
    assert code == 0, s
    assert s["outcomes"] == {"e-mail found in its website's archived pages (Common Crawl)": 1}
    rows = {r["value"]: r for r in db.q("SELECT * FROM contacts WHERE place_key='k1' AND kind='email'")}
    assert rows["hello@leafcafe.in"]["source"] == "archive" and rows["hello@leafcafe.in"]["confidence"] != "low"
    assert rows["hello@leafcafe.in"]["source_url"] == "https://www.leafcafe.in/contact"
    assert s["archive"]["pages read from the archive"] == 2 and s["archive"]["index lookups"] == 1


def test_archive_that_says_slow_down_is_left_alone_for_the_run(tmp_path):
    db = DB(str(tmp_path / "b.sqlite"))
    with db.tx():
        for i in range(2):
            place(db, f"k{i}", f"Shop Number {i}", website=f"https://shop{i}.in/")
    sites = {"https://index.commoncrawl.org/collinfo.json": (200, json.dumps([{"id": "CC-MAIN-2026-38"}]), "application/json"),
             "https://index.commoncrawl.org/CC-MAIN-2026-38-index": (503, "Please slow down", "text/plain")}
    http = FakeHttp(router_for(sites))
    code, s = EmailHunt(make_config(), db, limit=10, use_sheets=False, http=http, resolver=FakeResolver(set()),
                        mx=MXChecker(enabled=False), workers=1).run()
    assert code == 0, s
    assert s["outcomes"] == {"website unreachable": 2, "unreachable because: page not found (404)": 2}
    assert s["archive"]["index lookups"] == 1                                      # asked once, then no more
    assert sum(1 for _, u in http.calls if "CC-MAIN-2026-38-index" in u) == 1


class FakeSearch:
    def __init__(self, results: dict[str, list[Result]]):
        self.results, self.queries = results, []
        self.stats = {"yahoo": {"ok": 0, "blocked": 0, "empty": 0, "error": 0}}

    def available(self) -> bool:
        return True

    def search(self, q: str) -> list[Result]:
        self.queries.append(q)
        self.stats["yahoo"]["ok"] += 1
        return self.results.get(q, [])


def test_web_search_keeps_only_addresses_tied_to_the_business(tmp_path):
    db = DB(str(tmp_path / "c.sqlite"))
    with db.tx():
        place(db, "k1", "Joe's Diner", category="restaurant")                      # no website
        db.add_contact("k1", "phone", "+15125550142", source="overture", confidence="medium")
    results = [
        Result("Joe's Diner - Austin, TX | Facebook", "https://www.facebook.com/joesdineratx",
               "Joe's Diner. Classic breakfast all day. Contact: joesdineratx@gmail.com", "yahoo"),
        Result("Best diners in Austin", "https://www.austinfoodguide.com/diners",
               "Our picks for breakfast... Send tips to tips@austinfoodguide.com", "yahoo"),
        Result("Joe's Diner catering", "https://www.cateringlist.com/joes-diner-austin",
               "Joe's Diner, 1200 Main St, Austin. Call (512) 555-0142 or email orders@jdkitchenatx.com", "yahoo"),
        Result("Mike's Grill", "https://www.cateringlist.com/mikes-grill",
               "Mike's Grill (512) 555-0142 shares a line with ... email mike@mikesgrill.com", "yahoo"),
    ]
    search = FakeSearch({'"Joe\'s Diner" Austin email': results})
    code, s = EmailHunt(make_config(**US), db, limit=10, use_sheets=False, http=FakeHttp(router_for({})),
                        resolver=FakeResolver(set()), mx=MXChecker(enabled=False), workers=1, search=search).run()
    assert code == 0, s
    assert s["outcomes"]["e-mail found by web search (published elsewhere)"] == 1
    rows = {r["value"]: r for r in db.q("SELECT * FROM contacts WHERE place_key='k1' AND kind='email'")}
    assert set(rows) == {"joesdineratx@gmail.com", "orders@jdkitchenatx.com"}     # nothing of the guide or of Mike's
    assert rows["joesdineratx@gmail.com"]["source"] == "search" and rows["joesdineratx@gmail.com"]["confidence"] == "medium"
    assert rows["joesdineratx@gmail.com"]["source_url"] == "https://www.facebook.com/joesdineratx"
    assert "name and phone number" in rows["orders@jdkitchenatx.com"]["label"]
    assert search.queries == ['"Joe\'s Diner" Austin email']                      # found: no second query


def test_search_queries_and_ties():
    assert queries_for("Joe's Diner", "Austin", ["+15125550142"], "US") == ['"Joe\'s Diner" Austin email',
                                                                          '"(512) 555-0142" email']
    assert tie_to_business("hello@joesdiner.com", "Joe's Diner", "joesdiner.com", "", []) == "same domain as the website"
    assert tie_to_business("info@yelp.com", "Joe's Diner", "", "Joe's Diner (512) 555-0142 info@yelp.com",
                           ["+15125550142"]) == ""                                  # a platform's own address
    assert tie_to_business("owner@gmail.com", "Joe's Diner", "", "Joe's Diner call 512 555 0142 owner@gmail.com",
                           ["+15125550142"]) == "shown with the business's name and phone number"
