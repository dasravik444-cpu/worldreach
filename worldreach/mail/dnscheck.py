"""Is a sending domain set up so that Gmail, Outlook and Yahoo accept its mail? ( wr dns yourdomain.com )

Since 2024 (Gmail, Yahoo) and May 2025 (Outlook) mail from a domain without SPF and DKIM is refused or put in spam,
and senders of volume also need DMARC. A free @gmail.com or @outlook.com address has all of this done by the
provider; this check matters for a mailbox on your own domain.
"""
from __future__ import annotations

FREE_HOSTS = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "yahoo.com",
              "icloud.com", "zohomail.com", "proton.me", "protonmail.com"}
# DKIM is published under <selector>._domainkey.<domain>; these are the selectors the big providers use.
DKIM_SELECTORS = ("google", "selector1", "selector2", "zoho", "zmail", "default", "k1", "s1", "s2", "fm1", "mail",
                  "dkim", "protonmail")


def _txt(resolver, name: str) -> list[str]:
    try:
        return ["".join(part.decode("utf-8", "replace") if isinstance(part, bytes) else str(part) for part in r.strings)
                for r in resolver.resolve(name, "TXT")]
    except Exception:  # noqa: BLE001 - no such record
        return []


def check_domain(domain: str, resolver=None) -> list[tuple[str, bool, str]]:
    """[(what, ok, detail)] for MX, SPF, DKIM and DMARC of a domain."""
    domain = domain.strip().lower().rsplit("@", 1)[-1]
    if domain in FREE_HOSTS:
        return [("provider", True, f"{domain} is a mail provider's own domain: SPF, DKIM and DMARC are done by it")]
    if resolver is None:
        import dns.resolver

        resolver = dns.resolver.Resolver()
        resolver.lifetime = 6.0
    out = []
    try:
        mx = sorted(str(r.exchange).rstrip(".") for r in resolver.resolve(domain, "MX"))
    except Exception:  # noqa: BLE001
        mx = []
    out.append(("MX", bool(mx), ", ".join(mx[:3]) if mx else "no mail server: replies to you would bounce"))
    spf = [t for t in _txt(resolver, domain) if t.lower().startswith("v=spf1")]
    if len(spf) == 1:
        soft = spf[0].rstrip().endswith(("~all", "-all"))
        out.append(("SPF", True, spf[0][:120] + ("" if soft else "  (end it with ~all or -all)")))
    else:
        out.append(("SPF", False, "no SPF record" if not spf else "more than one SPF record: only one is allowed"))
    found = [s for s in DKIM_SELECTORS if any("p=" in t for t in _txt(resolver, f"{s}._domainkey.{domain}"))]
    out.append(("DKIM", bool(found), "selector " + ", ".join(found) if found else
                "no DKIM key found under the usual names: switch DKIM on in your mail provider's admin page"))
    dmarc = [t for t in _txt(resolver, f"_dmarc.{domain}") if t.lower().startswith("v=dmarc1")]
    out.append(("DMARC", bool(dmarc), dmarc[0][:120] if dmarc else
                'no DMARC record: add a TXT record _dmarc with "v=DMARC1; p=none; rua=mailto:you@' + domain + '"'))
    return out
