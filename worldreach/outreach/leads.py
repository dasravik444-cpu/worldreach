"""Read the lead tabs of the Google Sheet ("Leads US", "Leads UK" ...) into Lead records.

The Sheet is the durable record: a lead's Status cell says what happened to it, and anything the owner types there
("Customer", "Called", "Do not contact") means hands off.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from leadgen.enrich.emails import FREE_PROVIDERS
from leadgen.enrich.phones import parse_phone
from leadgen.sheets import _tab_ref, col_letter

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}$")
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com",
             "aol.com", "protonmail.com", "proton.me", "ymail.com", "zoho.com", "msn.com", "me.com", "mail.com",
             "gmx.com", "gmx.de", "web.de", "yahoo.co.uk", "hotmail.co.uk", "btinternet.com", "sky.com",
             "comcast.net", "att.net", "verizon.net", "sbcglobal.net", "bellsouth.net", "cox.net"} | FREE_PROVIDERS

COLUMNS = ["Lead ID", "Business Name", "Category", "Area", "Address", "Phones", "WhatsApp", "Emails", "Contact Person",
           "Website", "Priority", "Key", "Status", "Other Contacts (unverified)", "Signals", "USP", "Legal Form",
           "Contact Sources"]
# Legal forms (as the Leads sheet shows them) of incorporated businesses: in the UK and Ireland only these may be
# e-mailed without having asked first.
COMPANY_FORMS = {"GmbH/UG/AG", "Ltd/LLP/PLC", "Pty Ltd", "LLC/Inc"}

# Statuses the system writes. A lead whose Status is blank, "New" or one of these is the automation's; anything
# else typed by the owner means hands off.
STATUS_EMAILED = "Emailed"
STATUS_FOLLOWUP = "Emailed (follow-up {n})"
STATUS_REPLIED = "Replied - read it"
STATUS_INTERESTED = "Interested - call now"
STATUS_OPTED_OUT = "Not interested (opted out)"
STATUS_BOUNCED = "Email bounced"
STATUS_DONE = "Emailed - no reply"
STATUS_OPTED_IN = "Opted in"            # typed by the owner: the business asked to hear from us
STATUS_WHATSAPP = "WhatsApp sent"
STATUS_SKIPPED = "No usable e-mail"
SYSTEM_STATUSES = {"", "new", STATUS_EMAILED.lower(), STATUS_REPLIED.lower(), STATUS_INTERESTED.lower(),
                   STATUS_OPTED_OUT.lower(), STATUS_BOUNCED.lower(), STATUS_DONE.lower(), STATUS_OPTED_IN.lower(),
                   STATUS_WHATSAPP.lower(), STATUS_SKIPPED.lower()} | \
                  {STATUS_FOLLOWUP.format(n=n).lower() for n in range(1, 6)}
FRESH = ("", "new", STATUS_OPTED_IN.lower())       # never contacted


@dataclass
class Lead:
    key: str
    lead_id: str = ""
    row: int = 0
    business: str = ""
    category_label: str = ""
    category_key: str = ""
    area: str = ""
    emails: list[str] = field(default_factory=list)
    unverified_emails: list[str] = field(default_factory=list)
    phones: list[tuple[str, str]] = field(default_factory=list)     # (E.164, type label)
    whatsapp: list[str] = field(default_factory=list)                # numbers the business publishes as WhatsApp
    person: str = ""
    website: str = ""
    priority: str = ""
    status: str = ""
    signals: str = ""
    usp: str = ""                       # the business's own one-line claim (from its website), if any
    address: str = ""
    legal_form: str = ""
    email_sources: str = ""
    market: str = ""                    # "us": the country folder
    country: str = ""                   # "US"
    tz: str = ""                        # the business's time zone (its city's)
    city: str = ""

    @property
    def email_rank(self) -> int:
        """How sure the address still works, by where it was found: 0 the business's own website now, 1 open data,
        2 a web search, 3 only an old copy of its website."""
        s = self.email_sources.lower()
        if not s or "website" in s:
            return 0
        if "open data" in s or "overture" in s or "openstreetmap" in s:
            return 1
        if "search" in s:
            return 2
        if "archive" in s:
            return 3
        return 1

    @property
    def is_company(self) -> bool:
        return self.legal_form.strip() in COMPANY_FORMS

    @property
    def objects_to_advertising(self) -> bool:
        return "objects to advertising" in self.signals.lower()

    @property
    def opted_in(self) -> bool:
        return self.status.strip().lower() == STATUS_OPTED_IN.lower()

    @property
    def system_managed(self) -> bool:
        return self.status.strip().lower() in SYSTEM_STATUSES

    @property
    def fresh(self) -> bool:
        return self.status.strip().lower() in FRESH

    @property
    def first_name(self) -> str:
        name = re.sub(r"\(.*?\)", "", self.person.split("\n")[0]).strip()
        first = name.split(" ")[0].strip(" ,.") if name else ""
        return first if first.isalpha() and len(first) > 1 else ""

    def mobiles(self) -> list[str]:
        return [e164 for e164, label in self.phones
                if label.lower().startswith("mobile") and not label.lower().startswith("mobile/landline")]


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def _lines(cell) -> list[str]:
    return [x.strip() for x in str(cell or "").split("\n") if x.strip()]


def _numbers(cell, region: str) -> list[tuple[str, str]]:
    out = []
    for line in _lines(cell):
        number, _, rest = line.partition("(")
        parsed = parse_phone(number.strip(), region)
        if parsed and parsed[0] not in [e for e, _ in out]:
            out.append((parsed[0], rest.rstrip(")").strip() or parsed[1]))
    return out


def _email_sources(cell) -> str:
    """The e-mail part of Contact Sources: "phone: website; email: archive, web search" -> "archive, web search"."""
    m = re.search(r"(?:^|;)\s*email:\s*([^;]*)", str(cell or ""))
    return m.group(1).strip() if m else ""


def parse_lead(values: dict, row: int, market) -> Lead | None:
    key = str(values.get("Key") or "").strip()
    if not key:
        return None
    label = str(values.get("Category") or "").strip()
    cat_key = next((c["key"] for c in market.categories
                    if str(c.get("label", "")).lower() == label.lower() or c["key"] == label), "")
    emails: list[str] = []
    for e in _lines(values.get("Emails")):
        e = e.split(" ")[0].strip().lower()
        if EMAIL_RE.match(e) and e not in emails:
            emails.append(e)
    unverified: list[str] = []
    for line in _lines(values.get("Other Contacts (unverified)")):
        if line.lower().startswith("email:"):
            e = line.split(":", 1)[1].strip().split(" ")[0].strip().lower()
            if EMAIL_RE.match(e) and e not in emails and e not in unverified:
                unverified.append(e)
    lead_id = str(values.get("Lead ID") or "").strip()
    return Lead(key=key, lead_id=lead_id, row=row, business=str(values.get("Business Name") or "").strip(),
                category_label=label, category_key=cat_key, area=str(values.get("Area") or "").strip(),
                emails=emails, unverified_emails=unverified, phones=_numbers(values.get("Phones"), market.country),
                whatsapp=[e for e, _ in _numbers(values.get("WhatsApp"), market.country)],
                person=str(values.get("Contact Person") or "").strip(), website=str(values.get("Website") or "").strip(),
                priority=str(values.get("Priority") or "").strip(), status=str(values.get("Status") or "").strip(),
                signals=str(values.get("Signals") or "").strip(), usp=str(values.get("USP") or "").strip(),
                address=str(values.get("Address") or "").strip(), legal_form=str(values.get("Legal Form") or "").strip(),
                email_sources=_email_sources(values.get("Contact Sources")), market=market.code,
                country=market.country, tz=market.tz_of(lead_id), city=market.city_of(lead_id))


def read_leads(client, market) -> list[Lead]:
    """The market's lead tab: only the columns outreach needs, in one batched request. A tab that does not exist
    yet (no city of that market searched so far) is simply empty."""
    if market.leads_tab not in client.tabs():
        return []
    ref = _tab_ref(market.leads_tab)
    head = client.get_values(f"{ref}!A1:AZ1")
    header = [h.strip() for h in (head[0] if head else [])]
    present = [c for c in COLUMNS if c in header]
    if "Key" not in present:
        return []
    cols = client.batch_get_columns([f"{ref}!{col_letter(header.index(c))}2:{col_letter(header.index(c))}"
                                     for c in present])
    n = max((len(c) for c in cols), default=0)
    leads = []
    for i in range(n):
        values = {name: (cols[j][i] if i < len(cols[j]) else "") for j, name in enumerate(present)}
        lead = parse_lead(values, i + 2, market)
        if lead:
            leads.append(lead)
    return leads
