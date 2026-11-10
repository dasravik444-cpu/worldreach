"""Web search for a business's published e-mail address, when its own website has none (or it has no website).

Many small businesses publish their address somewhere else: their Facebook page, a chamber of commerce or
tourism listing, a local news or events page, a catering or wedding directory. A search like
'"Joe's Diner" Austin email' shows those pages with the address in the result text.

An address is kept only when it is clearly the business's own:
- it is at the business's website domain, or carries its name (joesdiner@gmail.com, info@joesdiner.com), or
- the same search result also shows the business's phone number and its name.
Addresses of the directory or page itself, or of other businesses on it, are left out. Nothing is guessed:
every address kept was published, and the result page it came from is stored as its source.
"""
from __future__ import annotations

import re

from ..net import BreakerOpen, FetchError
from ..quality import _is_common, distinctive_tokens, is_aggregator, norm_text
from .emails import FREE_PROVIDERS, find_emails_in_text, related_email
from .phones import parse_phone

# Pages whose addresses are never the business's own (platform support, review sites...).
NOT_THE_BUSINESS = ("yelp.", "tripadvisor.", "facebook.com/help", "google.", "bbb.org", "yellowpages.", "mapquest.",
                    "doordash.", "ubereats.", "grubhub.", "opentable.", "toasttab.")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _phone_in(text: str, phones: list[str]) -> bool:
    """One of the business's numbers appears in the text, written any way (512-555-0142, (512) 555 0142...)."""
    d = _digits(text)
    return any(len(_digits(p)) >= 10 and _digits(p)[-10:] in d for p in phones)


def _name_in(text: str, name: str) -> bool:
    """The business's whole name, or its unusual words, appear in the text."""
    low = " " + norm_text(text or "") + " "
    full = norm_text(name or "")
    if len(full) >= 6 and f" {full} " in low:
        return True
    words = [norm_text(w) for w in distinctive_tokens(name) if len(w) >= 4 and not _is_common(w)]
    return bool(words) and all(f" {w} " in low for w in words[:2] if w)


def tie_to_business(email: str, name: str, site_host: str, text: str, phones: list[str]) -> str:
    """Why this address (in a search result's text) is the business's own, or '' when nothing shows it."""
    tie = related_email(email, name, site_host)
    if tie:
        return tie
    domain = email.split("@", 1)[1]
    if _phone_in(text, phones) and _name_in(text, name) and (domain in FREE_PROVIDERS or not is_aggregator("https://" + domain)):
        return "shown with the business's name and phone number"
    return ""


def queries_for(name: str, city: str, phones: list[str], region: str) -> list[str]:
    out = [f'"{name}" {city} email'.strip()]
    if phones:
        parsed = parse_phone(phones[0], region)
        if parsed:
            d = _digits(parsed[0])[-10:]
            if len(d) == 10 and region == "US":
                out.append(f'"({d[:3]}) {d[3:6]}-{d[6:]}" email')
            else:
                out.append(f'"{phones[0]}" email')
    return out


def search_emails(ws, name: str, city: str, phones: list[str], site_host: str, region: str,
                  max_queries: int = 2) -> dict[str, tuple[str, str, str]]:
    """e-mail -> (result URL, result text, why it is theirs). Stops at the first query that finds one."""
    found: dict[str, tuple[str, str, str]] = {}
    for q in queries_for(name, city, phones, region)[:max_queries]:
        try:
            results = ws.search(q)
        except (BreakerOpen, FetchError):
            break
        for res in results[:10]:
            if any(b in (res.url or "").lower() for b in NOT_THE_BUSINESS) and "facebook.com" not in (res.url or ""):
                continue
            text = f"{res.title} {res.snippet}"
            for e in find_emails_in_text(text):
                tie = tie_to_business(e, name, site_host, text, phones)
                if tie and e not in found:
                    found[e] = (res.url, text[:300], tie)
        if found:
            break
    return found
