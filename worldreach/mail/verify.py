"""Is this address worth an e-mail? Checked before the first e-mail to it, because every bounce costs the sending
mailbox some of its reputation (above about 3% bounces mail starts landing in spam).

What is checked, without contacting the recipient's mail server (probing addresses from a home connection is
unreliable and looks like an attack):
  - the form of the address, and mistyped provider names (gmial.com, hotmial.com, yaho.com ...);
  - mailboxes nobody reads or that are not the business (noreply@, abuse@, postmaster@, privacy@ ...);
  - throw-away address services;
  - the domain's mail servers (DNS MX): a domain with none, or that says it takes no mail, would bounce.
Unknown (DNS not answering) never drops an address: it is tried, and a real bounce is learned from.
"""
from __future__ import annotations

import re

EMAIL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%+'-]{0,63}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                      r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,24}$")
DEAD_LOCAL = re.compile(r"^(no-?reply|do-?not-?reply|donotreply|mailer-daemon|postmaster|abuse|bounces?|privacy|dpo|gdpr|"
                        r"legal|dmca|security|hostmaster|webmaster|root|null|devnull|unsubscribe|spam|noc|example|test)"
                        r"([._+-].*)?$", re.I)
# Lists and departments that are not the owner or the front desk: a pitch there is unread at best, reported at worst.
WRONG_DESK = re.compile(r"^(careers?|jobs?|recruit\w*|hr|press|media|pr|investors?|billing|invoices?|accounts?|payable|"
                        r"receivable|legal|compliance|it|tech|support|helpdesk|orders?|returns?|wholesale|donations?)$", re.I)
TYPO_DOMAINS = {
    "gmial.com", "gmai.com", "gmal.com", "gamil.com", "gnail.com", "gmail.co", "gmail.con", "gmail.cm", "gmaill.com",
    "gmail.om", "gmali.com", "hotmial.com", "hotmai.com", "hotmal.com", "hotmail.co", "hotmail.con", "homail.com",
    "outlok.com", "outloo.com", "outlook.co", "outlook.con", "yaho.com", "yahooo.com", "yahoo.co", "yahoo.con",
    "yhaoo.com", "yahho.com", "icloud.co", "icloud.con", "iclould.com", "aol.co", "aol.con",
}
DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "temp-mail.org", "yopmail.com",
    "trashmail.com", "sharklasers.com", "getnada.com", "throwawaymail.com", "maildrop.cc", "dispostable.com",
    "fakeinbox.com", "mailnesia.com", "mintemail.com", "tempr.email", "discard.email", "emailondeck.com",
}
# Placeholders website builders leave in a template.
PLACEHOLDER = re.compile(r"^(you|your|yourname|name|user|username|email|someone|john\.?doe|jane\.?doe|first\.?last|"
                         r"info@example|mail)@|@(example|domain|yourdomain|yoursite|website|email|test|sentry|wixpress)\.", re.I)


class Verifier:
    """check(address) -> ("ok" | "risky" | "bad", reason). bad: never send. risky: send only when allowed
    ([email] send_risky). Results per domain are remembered for the run."""

    def __init__(self, mx=None, null_mx=None):
        if mx is None:
            from leadgen.enrich.emails import MXChecker

            mx = MXChecker(enabled=True)
        self.mx = mx
        self.null_mx = null_mx          # callable(domain) -> True when the domain publishes "takes no mail" (MX ".")

    def check(self, address: str) -> tuple[str, str]:
        address = (address or "").strip().lower()
        if not EMAIL_RE.match(address) or ".." in address:
            return "bad", "not a valid e-mail address"
        local, _, domain = address.rpartition("@")
        if PLACEHOLDER.search(address):
            return "bad", "a placeholder address left in a website template"
        if DEAD_LOCAL.match(local):
            return "bad", f"{local}@ is not read by a person"
        if domain in TYPO_DOMAINS:
            return "bad", f"{domain} looks mistyped"
        if domain in DISPOSABLE:
            return "bad", "a throw-away address service"
        if self.null_mx is not None and self.null_mx(domain):
            return "bad", f"{domain} says it takes no mail"
        has = self.mx.has_mx(domain) if self.mx is not None else None
        if has is False:
            return "bad", f"{domain} has no mail server"
        if WRONG_DESK.match(local):
            return "risky", f"{local}@ is a department's mailbox, not the owner's"
        if has is None:
            return "risky", "the domain's mail server could not be checked now"
        return "ok", ""
