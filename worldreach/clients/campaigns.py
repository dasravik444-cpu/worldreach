"""The follow-ups for one client: who is due for which message today, the words, the sending, the record.

Reads the client's customers.csv fresh every run (the client sends a new export whenever they like: a customer whose
last visit moved forward has come back, and any win-back series for them ends and is counted as a return).
"""
from __future__ import annotations

import csv
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from leadgen.util import get_tz

from ..mail import build_message
from ..mail.verify import EMAIL_RE
from ..outreach.classify import NEGATIVE, NEGATIVE_SHORT, new_text, snippet

DEFAULTS = {
    "name": "", "kind": "default", "timezone": "America/Chicago", "review_link": "", "sender_name": "",
    "address": "", "notify_email": "", "mailbox": 1, "approved": False, "daily_limit": 100,
    "window_start": 9, "window_end": 18,
    "campaigns": {"review": True, "comeback": True, "winback": True, "payment": False,
                  "review_within_days": 7, "comeback_after_days": 42, "winback_after_days": 90,
                  "winback_days": [0, 6, 14], "payment_days": [0, 4, 9]},
    "words": {"visit": "visit", "offer": ""},      # "class", "stay", "appointment" ...; an optional come-back offer
    "texts": {},
}
WEEK = 7
# Column names a client's export may use.
COLUMNS = {"name": ("name", "first name", "firstname", "customer", "client", "member", "guest", "full name"),
           "email": ("email", "e-mail", "email address", "mail"),
           "last_visit": ("last_visit", "last visit", "visit", "last appointment", "last booking", "last class",
                          "checkout", "check-out", "last seen", "date"),
           "consent": ("consent", "marketing", "opt-in", "optin", "subscribed", "email consent", "agreed"),
           "unpaid": ("unpaid", "overdue", "balance", "amount due", "outstanding", "failed payment"),
           "due": ("due", "due date", "payment date")}
YES = {"yes", "y", "true", "1", "x", "ok", "subscribed", "opted in", "opt-in", "agreed"}

TEXTS = {
    "review": ("Thank you from {business}",
               "Hi {first},\n\nThank you for your {visit} at {business}. If you have a minute, a Google review "
               "helps other people find us:\n{review_link}\n\nShort or long, your honest opinion is what counts.\n\n"
               "{sender}\n{footer}"),
    "comeback": ("Time for your next {visit}?",
                 "Hi {first},\n\nIt has been a little while since your last {visit} at {business}, so this is just "
                 "a friendly reminder. If you would like to come in, simply reply to this e-mail and we will find "
                 "a time that suits you.{offer}\n\n{sender}\n{footer}"),
    "winback": [("We miss you at {business}",
                 "Hi {first},\n\nIt has been a while since we saw you at {business}, and we wanted to say hello. "
                 "If you would like to come back, just reply to this e-mail and we will set it up for you.{offer}"
                 "\n\n{sender}\n{footer}"),
                ("Still here for you",
                 "Hi {first},\n\nA short note in case my last one got buried: we would be glad to see you at "
                 "{business} again. A one-line reply is enough and we will take care of the rest.{offer}\n\n"
                 "{sender}\n{footer}"),
                ("One last note from {business}",
                 "Hi {first},\n\nThis is my last note. If now is not the right time, no problem at all, and we "
                 "won't write again. If you would like to come back one day, you know where to find us.\n\n"
                 "{sender}\n{footer}")],
    "payment": [("A payment at {business} did not go through",
                 "Hi {first},\n\nA quick note: your recent payment at {business}{amount} did not go through. It is "
                 "usually just a card that expired. You can update it at your next {visit}, or reply here and we "
                 "will sort it out together.\n\n{sender}\n{footer_plain}"),
                ("Reminder: your payment at {business}",
                 "Hi {first},\n\nJust a reminder that your payment at {business}{amount} is still open. If something "
                 "has changed on your side, reply and let us know; we are happy to help.\n\n{sender}\n{footer_plain}"),
                ("Your account at {business}",
                 "Hi {first},\n\nYour payment at {business}{amount} is still open, and we would not want your "
                 "membership to lapse over it. Please reply to this e-mail so we can sort it out.\n\n{sender}\n"
                 "{footer_plain}")],
}
# What a review request may never say (Google's review rules; the FTC rule on reviews; the CMA's guidance).
FORBIDDEN_REVIEW = re.compile(r"\b(5[\s-]?stars?|five[\s-]?stars?|discount|voucher|coupon|free\b|prize|raffle|"
                              r"in return|reward|gift|if you (were|are) happy|positive review)\b", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sent (id INTEGER PRIMARY KEY, email TEXT NOT NULL, campaign TEXT NOT NULL, step INTEGER NOT NULL,
  at REAL NOT NULL, day TEXT NOT NULL, visit TEXT, msgid TEXT, status TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sent_email ON sent(email);
CREATE TABLE IF NOT EXISTS stops (email TEXT PRIMARY KEY, reason TEXT, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS replies (id INTEGER PRIMARY KEY, email TEXT, at REAL NOT NULL, text TEXT, forwarded INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS returns (email TEXT NOT NULL, visit TEXT NOT NULL, after TEXT, at REAL NOT NULL, PRIMARY KEY(email, visit));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class ClientError(ValueError):
    pass


@dataclass
class Customer:
    email: str
    name: str = ""
    last_visit: date | None = None
    consent: bool = False
    unpaid: str = ""
    due: date | None = None

    @property
    def first(self) -> str:
        first = self.name.strip().split(" ")[0].strip(",.") if self.name.strip() else ""
        return first.capitalize() if first.isalpha() and len(first) > 1 else "there"


@dataclass
class Due:
    customer: Customer
    campaign: str
    step: int
    subject: str = ""
    body: str = ""
    note: str = field(default="")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def parse_date(text: str) -> date | None:
    """A date as booking systems export it: 2026-11-03 (also with a time), 11/03/2026, 3 Nov 2026 ..."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    text = text.split("T")[0].strip()
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y", "%B %d, %Y",
                "%m/%d/%y"):
        for candidate in (text, text.split(" ")[0]):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


class Client:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.id = self.folder.name
        path = self.folder / "client.toml"
        if not path.is_file():
            raise ClientError(f"no client '{self.id}': {path} does not exist (wr client new {self.id})")
        try:
            self.cfg = _merge(DEFAULTS, tomllib.loads(path.read_text(encoding="utf-8")))
        except tomllib.TOMLDecodeError as exc:
            raise ClientError(f"{path} is not valid: {exc}") from exc
        self.conn = sqlite3.connect(str(self.folder / "state.sqlite"), timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ the client's settings and list
    def problems(self) -> list[str]:
        c = self.cfg
        out = [f"client.toml: {k} is missing" for k in ("name", "sender_name") if not str(c.get(k) or "").strip()]
        if c["campaigns"]["review"] and not str(c["review_link"]).startswith("http"):
            out.append("client.toml: review_link is missing (the business's Google review link)")
        if not str(c.get("address") or "").strip():
            out.append("client.toml: address is missing (the business's postal address: the law asks for it in "
                       "marketing e-mails)")
        for name, text in self._all_texts():
            if name.startswith("review") and FORBIDDEN_REVIEW.search(text):
                out.append(f"the {name} text offers something or asks for a good review: Google's rules forbid it")
        if not (self.folder / "customers.csv").is_file():
            out.append("customers.csv is missing (the client's export)")
        return out

    def _all_texts(self) -> list[tuple[str, str]]:
        out = []
        for key in ("review", "comeback", "winback", "payment"):
            t = self._texts(key)
            for i, (subject, body) in enumerate(t if isinstance(t, list) else [t]):
                out.append((f"{key} {i + 1}", subject + "\n" + body))
        return out

    def _texts(self, campaign: str):
        own = (self.cfg.get("texts") or {}).get(campaign)
        if not own:
            return TEXTS[campaign]
        if isinstance(own, dict):
            return (own.get("subject", ""), own.get("body", ""))
        return [(x.get("subject", ""), x.get("body", "")) for x in own]

    def customers(self) -> list[Customer]:
        path = self.folder / "customers.csv"
        if not path.is_file():
            return []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            rows = list(csv.DictReader(fh, dialect=dialect))
        if not rows:
            return []
        head = {h.strip().lower(): h for h in rows[0] if h}
        col = {k: next((head[n] for n in names if n in head), None) for k, names in COLUMNS.items()}
        if not col["email"]:
            raise ClientError(f"{path}: no e-mail column found (name it email)")
        out, seen = [], set()
        for r in rows:
            email = str(r.get(col["email"]) or "").strip().lower()
            if not EMAIL_RE.match(email) or email in seen:
                continue
            seen.add(email)
            g = lambda k: str(r.get(col[k]) or "").strip() if col[k] else ""  # noqa: E731
            unpaid = g("unpaid")
            out.append(Customer(email=email, name=g("name"), last_visit=parse_date(g("last_visit")),
                                consent=g("consent").lower() in YES,
                                unpaid="" if unpaid.lower() in ("", "0", "0.00", "no", "n", "false", "paid") else unpaid,
                                due=parse_date(g("due"))))
        return out

    # ------------------------------------------------------------------ who is due
    def _last(self, email: str, campaign: str | None = None):
        if campaign:
            return self.conn.execute("SELECT * FROM sent WHERE email=? AND campaign=? AND status='sent' ORDER BY at DESC LIMIT 1",
                                     (email, campaign)).fetchone()
        return self.conn.execute("SELECT * FROM sent WHERE email=? AND status='sent' ORDER BY at DESC LIMIT 1",
                                 (email,)).fetchone()

    def _series(self, email: str, campaign: str, visit: str) -> list:
        return self.conn.execute("SELECT * FROM sent WHERE email=? AND campaign=? AND visit=? AND status='sent' ORDER BY at",
                                 (email, campaign, visit)).fetchall()

    def note_returns(self, customers: list[Customer], now: float) -> int:
        """A customer we wrote a come-back or win-back to whose last visit is now later than when we wrote: back."""
        n = 0
        for c in customers:
            if not c.last_visit:
                continue
            row = self.conn.execute("SELECT campaign, day FROM sent WHERE email=? AND campaign IN ('winback','comeback') "
                                    "AND status='sent' ORDER BY at DESC LIMIT 1", (c.email,)).fetchone()
            if row and c.last_visit.isoformat() > row["day"]:
                cur = self.conn.execute("INSERT OR IGNORE INTO returns(email, visit, after, at) VALUES(?,?,?,?)",
                                        (c.email, c.last_visit.isoformat(), row["campaign"], now))
                n += cur.rowcount
        return n

    def due_today(self, now: float | None = None) -> list[Due]:
        """Today's messages, the most time-critical first, within the client's daily limit."""
        now = time.time() if now is None else now
        cam = self.cfg["campaigns"]
        today = datetime.fromtimestamp(now, get_tz(self.cfg["timezone"])).date()
        stops = {r["email"] for r in self.conn.execute("SELECT email FROM stops")}
        customers = self.customers()
        self.note_returns(customers, now)
        out: list[Due] = []
        for c in customers:
            if c.email in stops:
                continue
            last_any = self._last(c.email)
            recently = last_any is not None and now - last_any["at"] < WEEK * 86400
            visit = c.last_visit.isoformat() if c.last_visit else ""
            age = (today - c.last_visit).days if c.last_visit else None
            # 1. a missed payment: not marketing (it is about their own account), so consent is not the question
            if cam["payment"] and c.unpaid:
                key = f"unpaid:{c.due.isoformat() if c.due else c.unpaid}"
                done = self._series(c.email, "payment", key)
                days = cam["payment_days"]
                if len(done) < len(days) and (not done or now - done[0]["at"] >= days[len(done)] * 86400):
                    out.append(Due(c, "payment", len(done) + 1, note=key))
                continue                            # nothing else while a payment is open
            if not c.consent or age is None or age < 0:
                continue
            # 2. a thank-you with the review link, once per visit, soon after it
            if cam["review"] and 1 <= age <= cam["review_within_days"] and not self._series(c.email, "review", visit):
                asked = self._last(c.email, "review")
                if not (asked and now - asked["at"] < 90 * 86400):
                    out.append(Due(c, "review", 1, note=visit))
                    continue
            # 3. win-back: a series, for customers gone for months (it may run on although a message went out
            #    this week, because its own spacing is what counts)
            if cam["winback"] and age >= cam["winback_after_days"]:
                done = self._series(c.email, "winback", visit)
                days = cam["winback_days"]
                if len(done) < len(days) and (not done or now - done[0]["at"] >= days[len(done)] * 86400):
                    if done or not recently:
                        out.append(Due(c, "winback", len(done) + 1, note=visit))
                continue
            # 4. come-back: one reminder when they are due again
            if cam["comeback"] and age >= cam["comeback_after_days"] and not recently and \
                    not self._series(c.email, "comeback", visit):
                out.append(Due(c, "comeback", 1, note=visit))
        order = {"payment": 0, "review": 1, "winback": 2, "comeback": 3}
        out.sort(key=lambda d: (order[d.campaign], -d.step))
        sent_today = self.conn.execute("SELECT COUNT(*) FROM sent WHERE day=? AND status='sent'",
                                       (today.isoformat(),)).fetchone()[0]
        out = out[:max(0, int(self.cfg["daily_limit"]) - sent_today)]
        for d in out:
            d.subject, d.body = self.compose(d)
        return out

    def compose(self, d: Due) -> tuple[str, str]:
        c = self.cfg
        t = self._texts(d.campaign)
        subject, body = t[min(d.step - 1, len(t) - 1)] if isinstance(t, list) else t
        offer = str(c["words"].get("offer") or "").strip()
        amount = d.customer.unpaid if re.search(r"\d", d.customer.unpaid) else ""
        ctx = {"first": d.customer.first, "business": c["name"], "visit": c["words"].get("visit") or "visit",
               "review_link": c["review_link"], "sender": c["sender_name"], "offer": f" {offer}" if offer else "",
               "amount": f" ({amount})" if amount else "",
               "footer": f"\n{c['name']}, {c['address']}\nNo more e-mails from us? Just reply STOP.",
               "footer_plain": f"\n{c['name']}, {c['address']}"}
        fill = lambda s: re.sub(r"\n{3,}", "\n\n", s.format_map(_Keep(ctx))).strip()  # noqa: E731
        return fill(subject), fill(body)

    # ------------------------------------------------------------------ sending and answers
    def in_hours(self, now: float) -> bool:
        local = datetime.fromtimestamp(now, get_tz(self.cfg["timezone"]))
        return int(self.cfg["window_start"]) <= local.hour < int(self.cfg["window_end"])

    def record(self, d: Due, now: float, msgid: str, status: str = "sent") -> None:
        day = datetime.fromtimestamp(now, get_tz(self.cfg["timezone"])).date().isoformat()
        self.conn.execute("INSERT INTO sent(email, campaign, step, at, day, visit, msgid, status) VALUES(?,?,?,?,?,?,?,?)",
                          (d.customer.email, d.campaign, d.step, now, day, d.note, msgid, status))

    def stop(self, email: str, reason: str, now: float | None = None) -> bool:
        cur = self.conn.execute("INSERT OR IGNORE INTO stops(email, reason, at) VALUES(?,?,?)",
                                (email.strip().lower(), reason, time.time() if now is None else now))
        return cur.rowcount > 0

    def run(self, mailbox, *, live: bool, now_fn=time.time, sleep_fn=time.sleep, gap: float = 40.0) -> dict:
        """Read the answers, then send what is due. Returns the numbers of this run."""
        now = now_fn()
        stats = {"due": 0, "sent": 0, "failed": 0, "replies": 0, "stops": 0, "note": ""}
        if live:
            stats.update(self.read_answers(mailbox, now))
        due = self.due_today(now)
        stats["due"] = len(due)
        if not live:
            return stats
        if not self.cfg["approved"]:
            stats["note"] = "not approved yet: set approved = true in client.toml once the client has read the texts"
            return stats
        if not self.in_hours(now):
            stats["note"] = "outside the client's sending hours"
            return stats
        notify = str(self.cfg.get("notify_email") or "").strip()
        for i, d in enumerate(due):
            if i:
                sleep_fn(gap)
            msg = build_message(sender_name=self.cfg["sender_name"], sender_addr=mailbox.address, to=d.customer.email,
                                subject=d.subject, body=d.body, unsubscribe=d.campaign != "payment")
            if notify:
                msg["Reply-To"] = f"{notify}, {mailbox.address}"
            res = mailbox.send(msg)
            if res.ok:
                self.record(d, now_fn(), res.msgid or msg["Message-ID"])
                stats["sent"] += 1
            elif res.status == "invalid":
                self.record(d, now_fn(), "", "bounced")
                self.stop(d.customer.email, "address rejected by the mail server", now_fn())
                stats["failed"] += 1
            else:
                stats["failed"] += 1
                stats["note"] = f"sending stopped: {res.status} {res.detail[:120]}"
                break
        mailbox.close()
        return stats

    def read_answers(self, mailbox, now: float) -> dict:
        """Customers' answers in the sending mailbox: a "stop" is final; everything else is kept for the client."""
        known = {r["email"] for r in self.conn.execute("SELECT DISTINCT email FROM sent")}
        if not known:
            return {"replies": 0, "stops": 0}
        cursor = self.conn.execute("SELECT value FROM meta WHERE key='cursor'").fetchone()
        import json

        try:
            events, new_cursor = mailbox.scan(known_emails=known, known_msgids={},
                                              cursor=json.loads(cursor[0]) if cursor else {})
        except Exception:  # noqa: BLE001 - the inbox not answering must not stop today's messages
            return {"replies": 0, "stops": 0}
        replies = stops = 0
        for ev in events:
            if ev.kind == "bounce":
                stops += self.stop(ev.email, "bounced", now)
                continue
            if ev.reply_kind == "auto":
                continue
            text = new_text(ev.text)
            first = text.split("\n")[0] if text else ""
            if ev.reply_kind == "negative" or NEGATIVE.search(text) or NEGATIVE_SHORT.match(first):
                stops += self.stop(ev.email, "asked to stop", now)
            self.conn.execute("INSERT INTO replies(email, at, text) VALUES(?,?,?)", (ev.email, now, snippet(text, 1000)))
            replies += 1
        self.conn.execute("INSERT INTO meta(key, value) VALUES('cursor', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (json.dumps(new_cursor),))
        return {"replies": replies, "stops": stops}

    # ------------------------------------------------------------------ the report for the client
    def report(self, days: int = 30, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        since = now - days * 86400
        per = {r["campaign"]: r["n"] for r in self.conn.execute(
            "SELECT campaign, COUNT(*) AS n FROM sent WHERE status='sent' AND at>=? GROUP BY campaign", (since,))}
        people = self.conn.execute("SELECT COUNT(DISTINCT email) FROM sent WHERE status='sent' AND at>=?", (since,)).fetchone()[0]
        returns = [dict(r) for r in self.conn.execute("SELECT email, visit, after FROM returns WHERE at>=? ORDER BY at", (since,))]
        replies = [dict(r) for r in self.conn.execute("SELECT email, at, text FROM replies WHERE at>=? ORDER BY at", (since,))]
        stops = self.conn.execute("SELECT COUNT(*) FROM stops WHERE at>=?", (since,)).fetchone()[0]
        return {"client": self.cfg["name"], "days": days, "messages": per, "people": people, "returns": returns,
                "replies": replies, "stops": stops}


class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


CLIENT_TOML = '''# One client. Fill it in, put the client's export next to it as customers.csv, then:  wr client preview {id}
name = ""                     # the business, as its customers know it: "Lotus Yoga"
sender_name = ""              # who signs the messages: "Maria at Lotus Yoga"
kind = "default"
timezone = "America/Chicago"  # the business's time zone
address = ""                  # the business's postal address (required in marketing e-mails)
review_link = ""              # its Google review link (Google Business Profile > Ask for reviews)
notify_email = ""             # the client's own e-mail: customers' replies also go there
mailbox = 1                   # which of your mailboxes (settings.txt MAILBOX_n) sends for this client
daily_limit = 100
approved = false              # true only after the client has read and approved the texts ( wr client preview )

[campaigns]
review = true                 # a thank-you with the Google review link, 1-7 days after a visit
comeback = true               # one reminder when a customer is due again ...
comeback_after_days = 42      # ... this many days after the last visit
winback = true                # up to three notes to customers who have not been in for ...
winback_after_days = 90       # ... this many days
payment = false               # reminders for customers marked unpaid in the list

[words]
visit = "visit"               # "class", "stay", "appointment", "cut", "service" ...
offer = ""                    # optional, added to come-back and win-back notes: "Your next class is on us."
'''
