"""Pretend mailboxes, a pretend clock and a pretend Sheet for the outreach tests and the simulation."""
from __future__ import annotations

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

from helpers import FakeSheetsSession

from leadgen.sheets import LEAD_COLUMNS, SheetsClient
from worldreach.mail.base import InboxEvent, Mailbox, SendResult
from worldreach.mail.verify import Verifier
from worldreach.outreach import config as C
from worldreach.outreach.engine import Engine
from worldreach.outreach.leads import Lead
from worldreach.outreach.store import Store
from worldreach.settings import MailboxConfig

SENDER = {"name": "Ravik Das", "business": "Aurenflow", "phone": "+91 98300 00000",
          "postal_address": "12 Park Street, Kolkata 700016, India", "notify_email": "owner@example.org"}


class Clock:
    """Time that only moves when told to (sleep moves it)."""

    def __init__(self, text: str = "2026-11-10 10:00", tz: str = "America/Chicago"):
        self.t = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz)).timestamp()
        self.slept = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds
        self.slept += seconds

    def set(self, text: str, tz: str = "America/Chicago") -> None:
        self.t = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz)).timestamp()


class FakeMX:
    def __init__(self, dead=()):
        self.dead = set(dead)

    def has_mx(self, domain: str):
        return domain not in self.dead


class FakeMailbox(Mailbox):
    """A mailbox that keeps what it was asked to send. invalid: addresses its server rejects; limit_at: the provider
    says "daily limit" from that many sends in 24 hours on; block_at: it refuses the n-th send as spam."""

    def __init__(self, address: str, kind: str = "gmail", *, clock: Clock | None = None, invalid=(), limit_at: int = 0,
                 block_at: int = 0, login_problem: str = ""):
        self.address, self.kind, self.clock = address, kind, clock
        self.invalid, self.limit_at, self.block_at, self.login_problem = set(invalid), limit_at, block_at, login_problem
        self.sent: list = []            # (time, message)
        self.attempts = 0
        self.inbox: list[InboxEvent] = []
        self.scans = 0

    def check(self) -> str:
        return self.login_problem

    def send(self, msg) -> SendResult:
        now = self.clock.now() if self.clock else 0.0
        to = str(msg["To"]).lower()
        self.attempts += 1
        if self.login_problem:
            return SendResult("auth", 535, self.login_problem)
        if self.limit_at and len([1 for t, _ in self.sent if t > now - 86400]) >= self.limit_at:
            return SendResult("limit", 550, "5.4.5 Daily user sending limit exceeded")
        if self.block_at and self.attempts == self.block_at:
            return SendResult("blocked", 550, "5.7.1 message blocked: likely unsolicited mail (spam)")
        if to in self.invalid:
            return SendResult("invalid", 550, "5.1.1 The email account that you tried to reach does not exist")
        self.sent.append((now, copy.deepcopy(msg)))
        return SendResult("sent")

    def scan(self, *, known_emails, known_msgids, cursor):
        self.scans += 1
        events, self.inbox = self.inbox, []
        return [e for e in events if e.email in known_emails], {"n": self.scans}

    def to(self) -> list[str]:
        return [str(m["To"]).lower() for _, m in self.sent]


def box(index: int = 1, kind: str = "gmail", address: str = "", **kw) -> MailboxConfig:
    address = address or f"sender{index}@{'outlook.com' if kind == 'outlook' else 'gmail.com'}"
    return MailboxConfig(index=index, kind=kind, address=address, password="x" * 16, client_id="cid", **kw)


def lead_row(n: int, *, prefix: str = "AUS", name: str = "", email: str = "", category: str = "Gym / Fitness",
             status: str = "", legal: str = "", website: str = "", whatsapp: str = "", phone: str = "", usp: str = "",
             person: str = "", sources: str = "email: website", signals: str = "") -> list:
    name = name or f"Iron Temple {n}"
    values = {"Lead ID": f"{prefix}-{n}", "Business Name": name, "Category": category, "Area": "Downtown",
              "Emails": email if email != "" else f"owner{n}@business{n}.com", "Website": website or f"https://business{n}.com",
              "Key": f"k-{prefix}-{n}", "Status": status, "Legal Form": legal, "WhatsApp": whatsapp, "Phones": phone,
              "USP": usp, "Contact Person": person, "Contact Sources": sources, "Signals": signals, "Priority": "Medium"}
    return [values.get(c, "") for c in LEAD_COLUMNS]


def sheet(tabs: dict[str, list[list]]) -> tuple[SheetsClient, FakeSheetsSession]:
    """A pretend Sheet with lead tabs: {"Leads US": [lead_row(...), ...]}."""
    session = FakeSheetsSession()
    for i, (tab, rows) in enumerate(tabs.items(), start=1):
        session.tabs[tab] = {"id": 100 + i, "rows": [list(LEAD_COLUMNS)] + [list(r) for r in rows]}
        session.next_id = max(session.next_id, 200)
    return SheetsClient("sheet-id", session=session), session


def tab(session: FakeSheetsSession, name: str) -> list[dict]:
    rows = session.tabs[name]["rows"]
    head = rows[0]
    return [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in rows[1:] if any(str(x) for x in r)]


def status_of(session: FakeSheetsSession, leads_tab: str, lead_id: str) -> str:
    return next(r["Status"] for r in tab(session, leads_tab) if r["Lead ID"] == lead_id)


def outreach_config(**overrides) -> dict:
    o = C._merge(C.DEFAULTS, {"mode": "live", "sender": SENDER, **overrides})
    C.validate(o)
    return o


_MARKETS: dict = {}


def markets(*codes: str):
    out = []
    for code in codes or ("us",):
        if code not in _MARKETS:
            _MARKETS[code] = C.load_market(code)
        out.append(_MARKETS[code])
    return out


def engine(store: Store, clock: Clock, boxes: list, mailers: dict, *, client=None, leads=None, o: dict | None = None,
           codes=("us",), dead_domains=(), **kw) -> Engine:
    import random

    return Engine(o or outreach_config(), store, boxes, markets(*codes), client=client, leads=leads, mailers=mailers,
                  now_fn=clock.now, sleep_fn=clock.sleep, rng=random.Random(7),
                  verifier=Verifier(mx=FakeMX(dead_domains)), **kw)


def make_leads(n: int, *, prefix: str = "AUS", tz: str = "America/Chicago", market: str = "us", country: str = "US",
               start: int = 1, category: str = "gym", city: str = "Austin", legal: str = "") -> list[Lead]:
    return [Lead(key=f"k-{prefix}-{i}", lead_id=f"{prefix}-{i}", business=f"Iron Temple {i}", category_key=category,
                 category_label="Gym / Fitness", emails=[f"owner{i}@{prefix.lower()}biz{i}.com"],
                 website=f"https://{prefix.lower()}biz{i}.com", market=market, country=country, tz=tz, city=city,
                 legal_form=legal, email_sources="website")
            for i in range(start, start + n)]
