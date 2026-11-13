"""One outreach run (the robot starts one every hour): read the Sheet and every mailbox's inbox, send what is due now
from each mailbox, queue the WhatsApp messages, write everything back.

Safe by default: dry-run (nothing is sent) until the owner switches to live. Live, each mailbox follows its own
warm-up (ramp.py), e-mails go out only in the business's own office hours, a few minutes apart, every reply, bounce
and opt-out ends that conversation for good, and a mailbox stops by itself when its provider signals a limit or a
block, or when too many addresses bounce.

Several mailboxes share one memory, so a business is written to by exactly one of them, once.
"""
from __future__ import annotations

import math
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from leadgen.country import PACKS
from leadgen.enrich.phones import display_phone, parse_phone
from leadgen.sheets import SheetsClient, SheetsError
from leadgen.util import fmt_local, get_logger, get_tz, jdump

from ..mail import body_text, build_message, open_mailbox
from ..mail.lint import lint
from ..mail.verify import Verifier
from ..settings import ROOT
from . import ramp
from . import templates as T
from .classify import snippet, wants_overview
from .config import DAY_NAMES, minutes
from .leads import (FREE_MAIL, STATUS_BOUNCED, STATUS_DONE, STATUS_EMAILED, STATUS_FOLLOWUP, STATUS_INTERESTED,
                    STATUS_OPTED_OUT, STATUS_REPLIED, STATUS_SKIPPED, STATUS_WHATSAPP, Lead, email_domain, read_leads)
from .sheet import OutreachSheet
from .whatsapp import REASONS, result_code, wa_link

log = get_logger("outreach")
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
REPLY_LABEL = {"positive": "Interested", "negative": "Not interested", "other": "Replied"}
NEXT_STEP = {"positive": "Answer today: offer a 15-minute call (the overview went out by itself if marked so)",
             "negative": "Removed - they will not be contacted again",
             "other": "Read the reply and answer it yourself"}
NO_REPLY_AFTER_DAYS = 5
WA_SENT = ("sent", "replied", "interested", "not_interested")
WA_STALE_DAYS = 14
NETWORK_RETRIES, NETWORK_RETRY_S = 3, 60


@dataclass
class Item:
    kind: str            # new | followup | overview
    step: int
    email: str
    lead: Lead
    thread: object       # the conversation's row, None for a first e-mail
    box: str             # the mailbox that sends it (its address)


def _id_num(lead_id: str) -> int:
    digits = re.sub(r"\D", "", lead_id or "")
    return int(digits) if digits else 10**9


def business_keys(lead: Lead) -> set[str]:
    """What identifies the business behind a lead: its website's domain, and within a city its name without place
    words - two listings of one hotel must not get two e-mails."""
    from leadgen.enrich.emails import platform_of
    from leadgen.enrich.extract import host_of, registrable
    from leadgen.quality import core_name, tokens
    from leadgen.util import norm_text

    keys = set()
    site = lead.website.strip()
    host = host_of(site if "://" in site else "http://" + site) if site else ""
    if host:
        keys.add("site:" + (host if platform_of(host) else registrable(host)))
    place = {"branch", "outlet", "location"} | set(norm_text(lead.city).split())
    name = "".join(t for t in tokens(core_name(lead.business)) if t not in place)
    if len(name) >= 5:
        # within its own city only: "Elite Fitness" in Austin and in Denver are two businesses (one chain with one
        # website is caught by the website above)
        keys.add(f"name:{re.sub(r'[^A-Za-z]', '', lead.lead_id.split('-')[0]).upper()}:{name}")
    return keys


class Engine:
    def __init__(self, o: dict, store, boxes: list, markets: list, *, client=None, sheet_id: str = "", mailers=None,
                 leads: list[Lead] | None = None, live: bool | None = None, max_emails: int | None = None,
                 now_fn=time.time, sleep_fn=time.sleep, rng=None, verifier=None, test_to=(), bcc: str = "",
                 only_box: int = 0):
        self.o, self.store = o, store
        self.boxes = [b for b in boxes if not only_box or b.index == only_box]
        self.markets = {m.code: m for m in markets}
        self.client, self.sheet_id = client, sheet_id
        self.mailers = dict(mailers or {})         # address -> Mailbox (opened on first use)
        self.use_sheet = leads is None
        self.leads: list[Lead] = list(leads or [])
        self.live = (o["mode"] == "live") if live is None else live
        self.max_emails = max_emails
        self.now, self.sleep = now_fn, sleep_fn
        self.rng = rng or random.Random()
        self.verifier = verifier or Verifier()
        self.test_to = [a.strip() for a in test_to if a and "@" in a]
        self.bcc = bcc
        self.notes: list[str] = []
        self.alerts: list[str] = []                # for the owner's e-mail: pauses, logins that stopped working
        self.code = 0
        self.stats = {"new": 0, "followups": 0, "overviews": 0, "bounces": 0, "positive": 0, "negative": 0, "other": 0,
                      "skipped": 0, "wa_queued": 0, "wa_done": 0, "planned": 0, "not_emailed_by_rule": 0}
        self.status_updates: dict[str, dict[str, str]] = {}     # market -> lead key -> Status
        self.new_replies: list[dict] = []
        self.preview: list[list] = []
        self.wa_rows: list[list] = []
        self.sent_log: list[list] = []
        self.by_key: dict[str, Lead] = {}
        self.usable: list = []                     # mailboxes that may send in this run
        self.caps: dict[str, int] = {}

    # ------------------------------------------------------------------ small helpers
    def _day(self, ts: float | None = None) -> str:
        return datetime.fromtimestamp(self.now() if ts is None else ts, get_tz(self.o["email"]["day_tz"])).date().isoformat()

    def _mailer(self, box):
        if box.key not in self.mailers:
            self.mailers[box.key] = open_mailbox(box)
        return self.mailers[box.key]

    def _box(self, addr: str):
        return next((b for b in self.boxes if b.key == (addr or "").lower()), None)

    def _set_status(self, lead: Lead | None, status: str) -> None:
        if lead and lead.system_managed:
            self.status_updates.setdefault(lead.market, {})[lead.key] = status
            lead.status = status

    def _suppress_lead(self, lead: Lead | None, reason: str, source: str) -> None:
        if not lead:
            return
        for e in lead.emails + lead.unverified_emails:
            self.store.suppress(e, "email", reason, source)
        for number in [p for p, _ in lead.phones] + lead.whatsapp:
            self.store.suppress(number, "phone", reason, source)
        self.store.conn.execute("UPDATE threads SET stage='opted_out', next_due=NULL, updated_at=? "
                                "WHERE lead_key=? AND stage='active'", (self.now(), lead.key))

    def _score(self, lead: Lead) -> tuple:
        boost = set(self.o["email"].get("boost_categories") or [])
        return (PRIORITY_RANK.get(lead.priority.lower(), 3), 0 if lead.category_key in boost else 1,
                0 if lead.signals else 1, 0 if lead.usp else 1, _id_num(lead.lead_id))

    def _open_for(self, lead: Lead, ts: float | None = None) -> bool:
        """Is it office hours at this business right now?"""
        e = self.o["email"]
        local = datetime.fromtimestamp(self.now() if ts is None else ts, get_tz(lead.tz or e["day_tz"]))
        if DAY_NAMES[local.weekday()] not in e["days"] or local.date().isoformat() in [str(d) for d in e["skip_dates"]]:
            return False
        return minutes(e["window_start"]) <= local.hour * 60 + local.minute < minutes(e["window_end"])

    def _hours_left(self) -> int:
        """Hourly runs still to come today in which some market is in its office hours (at least 1)."""
        e = self.o["email"]
        now = self.now()
        latest = now
        # only the time zones we really have businesses in: with one city searched so far, the day's e-mails are
        # spread over that city's office hours, not over a whole continent's
        zones = {ld.tz for ld in self.leads if ld.tz and ld.system_managed and (ld.emails or ld.unverified_emails)} or \
            {m.default_tz for m in self.markets.values()}
        for name in zones:
            local = datetime.fromtimestamp(now, get_tz(name))
            if DAY_NAMES[local.weekday()] not in e["days"]:
                continue
            end = local.replace(hour=minutes(e["window_end"]) // 60, minute=minutes(e["window_end"]) % 60, second=0,
                                microsecond=0)
            if self._day(end.timestamp()) == self._day():
                latest = max(latest, end.timestamp())
        return max(1, math.ceil((latest - now) / 3600))

    def _sender_problem(self) -> str:
        s = self.o["sender"]
        missing = [k for k in ("name", "business") if not str(s.get(k) or "").strip()]
        need_address = [m.name for m in self.markets.values() if PACKS[m.country].rules.postal_address_required]
        if need_address and not str(s.get("postal_address") or "").strip():
            missing.append("postal_address")
        if missing:
            names = {"name": "SENDER_NAME", "business": "SENDER_BUSINESS", "postal_address": "POSTAL_ADDRESS"}
            hint = (f" (the law in {', '.join(need_address)} asks for a postal address in every sales e-mail)"
                    if "postal_address" in missing else "")
            return "fill in settings.txt: " + ", ".join(names[m] for m in missing) + hint
        if not self.boxes:
            return "no mailbox in settings.txt (MAILBOX_1=gmail, MAILBOX_1_ADDRESS, MAILBOX_1_PASSWORD)"
        return ""

    # ------------------------------------------------------------------ the run
    def run(self) -> tuple[int, dict]:
        if self.live:
            problem = self._sender_problem()
            if problem:
                self.notes.append(problem)
                return 1, self._summary("not started")
        sheet = None
        if self.use_sheet:
            try:
                if self.client is None:
                    if not self.sheet_id:
                        self.notes.append("no Google Sheet configured (WR_SHEET_ID in settings.txt)")
                        return 1, self._summary("not started")
                    self.client = SheetsClient(self.sheet_id)
                sheet = OutreachSheet(self.client, self.o["tabs"])
                sheet.ensure_tabs()
                for market in self.markets.values():
                    self.leads.extend(read_leads(self.client, market))
                self.by_key = {lead.key: lead for lead in self.leads}
                self._sync_dnc(sheet)
                self._sync_whatsapp(sheet)
            except SheetsError as exc:
                self.notes.append(f"Google Sheet error: {exc}")
                return 2, self._summary("sheet error")
        self.by_key = {lead.key: lead for lead in self.leads}
        self._ready_mailboxes()
        if self.test_to:
            self._send_test()
            return self.code, self._summary("test")
        self._check_inboxes()
        self._mark_no_reply()
        self._send_emails()
        self._whatsapp_queue()
        status = "ok"
        if sheet is not None:
            try:
                self._write_sheet(sheet)
            except SheetsError as exc:
                self.notes.append(f"Google Sheet error while saving results: {exc}")
                self.code = max(self.code, 2)
                status = "sheet error"
        self._notify_owner()
        for m in self.mailers.values():
            m.close()
        summary = self._summary(status)
        if sheet is not None and (self._did_something() or self.notes):
            try:
                sheet.append("report", [self._report_row()])
            except SheetsError:
                pass
        return self.code, summary

    def _did_something(self) -> bool:
        s = self.stats
        return any(s[k] for k in ("new", "followups", "overviews", "bounces", "positive", "negative", "other",
                                  "wa_queued", "planned"))

    def _ready_mailboxes(self) -> None:
        """The mailboxes whose settings are complete (a missing password is said once, plainly)."""
        self.usable = []
        for box in self.boxes:
            problem = box.problem()
            if problem:
                self.notes.append(f"mailbox {box.index} ({box.address or 'no address'}) not used: {problem}")
                self.code = max(self.code, 2) if self.live else self.code
            else:
                self.usable.append(box)

    # ------------------------------------------------------------------ the owner's input from the Sheet
    def _sync_dnc(self, sheet: OutreachSheet) -> None:
        for value, reason in sheet.read_dnc():
            v = value.strip()
            if v.startswith("@") and "." in v:
                self.store.suppress(v, "domain", reason or "added by owner", "sheet", in_sheet=True)
            elif "@" in v:
                self.store.suppress(v, "email", reason or "added by owner", "sheet", in_sheet=True)
            else:
                p = next((parse_phone(v, m.country) for m in self.markets.values() if parse_phone(v, m.country)), None)
                if p:
                    self.store.suppress(p[0], "phone", reason or "added by owner", "sheet", in_sheet=True)
            self.store.conn.execute("UPDATE suppression SET in_sheet=1 WHERE value=?", (v.lower(),))

    def _sync_whatsapp(self, sheet: OutreachSheet) -> None:
        for key, number, cell in sheet.read_whatsapp_results():
            code = result_code(cell)
            lead = self.by_key.get(key)
            p = parse_phone(number, lead.country if lead else "US") if number else None
            if not p:
                continue
            row = self.store.one("SELECT result FROM wa WHERE phone=?", (p[0],))
            if row is None:        # listed in the tab but unknown here (memory lost): never queue it twice
                self.store.conn.execute("INSERT OR IGNORE INTO wa(phone,lead_key,lead_id,business,reason,queued_day,result,"
                                        "updated_at) VALUES(?,?,?,?,?,?,?,?)",
                                        (p[0], key, lead.lead_id if lead else "", lead.business if lead else "", "listed",
                                         "", code, self.now()))
                row = {"result": ""}
            elif not code or row["result"] == code:
                continue
            self.store.conn.execute("UPDATE wa SET result=?, updated_at=? WHERE phone=?", (code, self.now(), p[0]))
            if code in WA_SENT:
                self.store.conn.execute("INSERT OR IGNORE INTO wa_sent(phone, day) VALUES(?,?)", (p[0], self._day()))
            if code:
                self.stats["wa_done"] += 1
            if code == "not_interested":
                self.store.suppress(p[0], "phone", "not interested (WhatsApp)", "whatsapp")
                self._suppress_lead(lead, "not interested (WhatsApp)", "whatsapp")
                self._set_status(lead, STATUS_OPTED_OUT)
            elif code == "interested":
                self._set_status(lead, STATUS_INTERESTED)
            elif code in ("sent", "replied") and lead and lead.fresh:
                self._set_status(lead, STATUS_WHATSAPP)          # one channel at a time: no e-mail on top

    # ------------------------------------------------------------------ inboxes
    def _check_inboxes(self) -> None:
        threads = self.store.q("SELECT email, msgids FROM threads")
        if not threads:
            return                      # nothing ever sent: no replies to read (and no hourly logins)
        known = {t["email"] for t in threads}
        msgids = {m: t["email"] for t in threads for m in self.store.msgids(t)}
        for box in self.usable:
            cursor = self.store.box(box.key).get("cursor") or {}
            try:
                events, cursor = self._mailer(box).scan(known_emails=known, known_msgids=msgids, cursor=cursor)
            except Exception as exc:  # noqa: BLE001 - an inbox problem must not stop sending or the Sheet update
                self.notes.append(f"could not read the inbox of {box.address}: {type(exc).__name__}: {str(exc)[:200]}")
                if self.live:
                    self.code = max(self.code, 2)
                continue
            with self.store.tx():
                for ev in events:
                    self._inbox_event(box, ev)
                self.store.set_box(box.key, cursor=cursor)

    def _inbox_event(self, box, ev) -> None:
        now = self.now()
        t = self.store.thread(ev.email)
        lead = self.by_key.get(t["lead_key"]) if t else None
        if ev.kind == "bounce":
            if t and t["stage"] != "bounced":
                self.store.conn.execute("UPDATE threads SET stage='bounced', next_due=NULL, updated_at=? WHERE email=?",
                                        (now, ev.email))
                self.store.conn.execute("INSERT INTO sends(email,lead_key,mailbox,step,sent_at,day,status,error) "
                                        "VALUES(?,?,?,?,?,?,?,?)", (ev.email, t["lead_key"], t["mailbox"] or box.key,
                                                                    t["step"], now, self._day(), "bounced", "bounce message"))
                self.store.suppress(ev.email, "email", "bounced (address does not exist)", "bounce")
                self.stats["bounces"] += 1
                self._set_status(lead, STATUS_BOUNCED)
            return
        if ev.reply_kind == "auto" or t is None or t["stage"] in ("replied", "opted_out") and ev.reply_kind == "other":
            return
        stage = "opted_out" if ev.reply_kind == "negative" else "replied"
        self.store.conn.execute("UPDATE threads SET stage=?, next_due=NULL, reply_kind=?, reply_at=?, reply_snippet=?, "
                                "updated_at=? WHERE email=?", (stage, ev.reply_kind, now, snippet(ev.text), now, ev.email))
        self.store.conn.execute("INSERT INTO replies(email,lead_key,mailbox,kind,received_at,snippet,ref) VALUES(?,?,?,?,?,?,?)",
                                (ev.email, t["lead_key"], box.key, ev.reply_kind, now, snippet(ev.text, 1000), ev.ref))
        self.stats[ev.reply_kind] += 1
        overview = False
        if ev.reply_kind == "negative":
            self.store.suppress(ev.email, "email", "asked not to be contacted", "reply")
            self._suppress_lead(lead, "asked not to be contacted", "reply")
            self._set_status(lead, STATUS_OPTED_OUT)
        elif ev.reply_kind == "positive":
            self._set_status(lead, STATUS_INTERESTED)
            self._queue_opted_in(lead)
            overview = self._send_overview(box, lead, self.store.thread(ev.email), ev.text)
        else:
            self._set_status(lead, STATUS_REPLIED)
        self.new_replies.append({"email": ev.email, "kind": ev.reply_kind, "text": ev.text, "lead": lead, "box": box.address,
                                 "lead_key": t["lead_key"], "lead_id": t["lead_id"], "business": t["business"],
                                 "overview": overview})

    def _send_overview(self, box, lead: Lead | None, t, text: str) -> bool:
        """A plain "yes, send it": the overview PDF goes back at once, in the same conversation, from the mailbox
        the business wrote to. Anything less clear is left to the owner."""
        a = self.o["auto_reply"]
        if not (a.get("enabled") and self.live and lead and t and not t["auto_replied"] and wants_overview(text)):
            return False
        if ramp.allowance(self.store, self.o, box, self._day(), self.now())[0] <= 0 or \
                ramp.room_24h(self.store, self.o, box, self.now()) <= 0:
            return False
        path = overview_pdf(self.o)
        attach = [(_pdf_name(self.o), path.read_bytes())] if path else None
        if attach is None:
            return False                # no PDF to send: the owner answers
        ids = self.store.msgids(t)
        subject = t["subject"] if (t["subject"] or "").lower().startswith("re:") else f"Re: {t['subject']}"
        msg = build_message(sender_name=box.name or self.o["sender"]["name"], sender_addr=box.address, to=t["email"],
                            subject=subject, body=T.auto_reply(lead, self.o, mailbox_name=box.name),
                            in_reply_to=ids[-1] if ids else "", references=ids, attachments=attach, unsubscribe=False)
        res = self._mailer(box).send(msg)
        if not res.ok:
            self.notes.append(f"the overview for {t['business']} could not be sent ({res.status}): answer them yourself")
            return False
        now = self.now()
        self.store.conn.execute("INSERT INTO sends(email,lead_key,mailbox,step,msgid,sent_at,day,status) VALUES(?,?,?,?,?,?,?,?)",
                                (t["email"], t["lead_key"], box.key, 0, res.msgid or msg["Message-ID"], now, self._day(), "sent"))
        self.store.conn.execute("UPDATE threads SET auto_replied=?, updated_at=? WHERE email=?", (now, now, t["email"]))
        self.stats["overviews"] += 1
        return True

    def _queue_opted_in(self, lead: Lead | None) -> None:
        """They said yes by e-mail: their WhatsApp number (if they publish one) goes to the top of the queue."""
        if not lead or not self.o["whatsapp"]["enabled"]:
            return
        numbers = lead.whatsapp + [m for m in lead.mobiles() if m not in lead.whatsapp]
        if not numbers:
            return
        phone = numbers[0]
        row = self.store.one("SELECT result, reason FROM wa WHERE phone=?", (phone,))
        if row is not None and (row["reason"] == "opted_in" or row["result"] == "not_interested"):
            return
        self.store.conn.execute(
            "INSERT INTO wa(phone,lead_key,lead_id,business,reason,queued_day,result,updated_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(phone) DO UPDATE SET reason='opted_in', queued_day=excluded.queued_day, result='', "
            "updated_at=excluded.updated_at", (phone, lead.key, lead.lead_id, lead.business, "opted_in", self._day(), "",
                                               self.now()))
        self.wa_rows.append(self._wa_row(lead, phone, "opted_in"))
        self.stats["wa_queued"] += 1

    def _mark_no_reply(self) -> None:
        cutoff = self.now() - NO_REPLY_AFTER_DAYS * 86400
        for t in self.store.q("SELECT email, lead_key FROM threads WHERE stage='completed' AND last_sent < ?", (cutoff,)):
            self.store.conn.execute("UPDATE threads SET stage='no_reply', updated_at=? WHERE email=?", (self.now(), t["email"]))
            self._set_status(self.by_key.get(t["lead_key"]), STATUS_DONE)

    # ------------------------------------------------------------------ e-mail: how many, to whom
    def _quotas(self) -> dict[str, int]:
        """What each usable mailbox may send in this run: its share of what is left of today's limit."""
        e = self.o["email"]
        day, now = self._day(), self.now()
        hours = self._hours_left()
        out: dict[str, int] = {}
        for box in self.usable:
            if not self.live:           # a dry run looks without fixing the day's limit or starting the warm-up
                d = ramp.describe(self.store, self.o, box, day, now)
                cap = d["cap_today"] or ramp.steps_for(self.o, box)[min(d["step"] - 1, len(d["steps"]) - 1)]
                left, why = (0, d["pause_reason"]) if d["paused_until"] else (max(0, cap - d["sent_today"]), "")
            else:
                left, why = ramp.allowance(self.store, self.o, box, day, now)
                cap = int(self.store.box(box.key).get("cap") or 0)
            self.caps[box.key] = cap
            if why:
                until = float(self.store.box(box.key).get("paused_until") or 0)
                self.notes.append(f"{box.address}: sending paused until {fmt_local(e['day_tz'], until)} ({why})")
            # this run's share of what is left of today, never more than fits into the run at the smallest gap, and
            # never past the provider's ceiling for any 24 hours
            budget = float(e["run_budget_minutes"]) * 60
            fits = int(0.95 * budget / float(e["min_gap_seconds"]))
            n = min(int(e["max_per_run"]), fits, math.ceil(left / hours),
                    ramp.room_24h(self.store, self.o, box, now, ahead=0.8 * budget)) if left > 0 else 0
            out[box.key] = min(n, left)
        if self.max_emails is not None:         # a test by hand: exactly that many in all, now
            total, capped = self.max_emails, {}
            for box in self.usable:
                capped[box.key] = min(total, max(out[box.key], 1 if not self.store.box(box.key).get("paused_until") else 0))
                total -= capped[box.key]
            out = capped
        return out

    def _send_emails(self) -> None:
        e = self.o["email"]
        if not e["enabled"] and self.max_emails is None:
            self.notes.append("e-mail sending is switched off ([email] enabled = false in config/outreach.toml)")
            return
        if self.max_emails == 0:
            self.notes.append("check only: replies and bounces read, nothing sent")
            return
        quotas = self._quotas()
        if not any(quotas.values()):
            return
        if self.live:
            for box in list(self.usable):
                if quotas.get(box.key) and (problem := self._mailer(box).check()):
                    self.notes.append(f"no e-mails from this mailbox: {problem}")
                    self.alerts.append(problem)
                    self.code = max(self.code, 2)
                    quotas[box.key] = 0
        items = self._pick(quotas)
        if not self.live:
            for item in items:
                msg = self._compose(item)
                body = body_text(msg)
                checks = lint(msg["Subject"], body, footer=T.context(item.lead, self.o)["footer"],
                              follow_up=item.kind != "new")
                self.preview.append([self._day(), item.lead.lead_id, item.lead.business, item.email, item.box,
                                     msg["Subject"], body, "; ".join(checks) or "OK", item.lead.key])
            self.stats["planned"] = len(self.preview)
            self.notes.append(f"dry-run: {len(self.preview)} e-mail(s) prepared, nothing sent")
            return
        self._send_all(items)

    def _pick(self, quotas: dict[str, int]) -> list[Item]:
        e = self.o["email"]
        now = self.now()
        left = dict(quotas)
        manual = self.max_emails is not None
        out: list[Item] = []
        sup = self.store.suppressed_values()
        blocked = lambda *vals: any(v and v.lower() in sup for v in vals)  # noqa: E731
        # 1. follow-ups that are due, from the mailbox that wrote the first e-mail
        for t in self.store.q("SELECT * FROM threads WHERE stage='active' AND next_due IS NOT NULL AND next_due<=? "
                              "ORDER BY next_due", (now,)):
            lead = self.by_key.get(t["lead_key"])
            if (self.use_sheet and lead is None) or (lead and not lead.system_managed) or \
                    blocked(t["email"], "@" + email_domain(t["email"])):
                self.store.conn.execute("UPDATE threads SET stage='stopped', next_due=NULL, updated_at=? WHERE email=?",
                                        (now, t["email"]))
                continue
            if lead and blocked(*[p for p, _ in lead.phones], *lead.whatsapp):
                self.store.conn.execute("UPDATE threads SET stage='opted_out', next_due=NULL, updated_at=? WHERE email=?",
                                        (now, t["email"]))
                continue
            lead = lead or self._stub(t)
            if left.get(t["mailbox"] or "", 0) <= 0 or not (manual or self._open_for(lead)):
                continue                # stays due: its mailbox is full or paused, or their office is closed
            out.append(Item("followup", t["step"] + 1, t["email"], lead, t, t["mailbox"]))
            left[t["mailbox"]] -= 1
        if not any(v > 0 for v in left.values()):
            return out
        # 2. first e-mails, best leads first
        used_emails = {r["email"] for r in self.store.q("SELECT email FROM threads")} | \
            {r["email"] for r in self.store.q("SELECT email FROM skipped")}
        used_leads = {r["lead_key"] for r in self.store.q("SELECT DISTINCT lead_key FROM threads")}
        recent = datetime.fromtimestamp(now - WA_STALE_DAYS * 86400, get_tz(e["day_tz"])).date().isoformat()
        marks = ",".join(f"'{r}'" for r in WA_SENT)
        used_leads |= {r["lead_key"] for r in self.store.q(
            f"SELECT DISTINCT lead_key FROM wa WHERE (result='' AND queued_day>=?) OR result IN ({marks})", (recent,))}
        used_domains = {r["domain"] for r in self.store.q("SELECT DISTINCT domain FROM threads WHERE domain IS NOT NULL")}
        used_business: set[str] = set()
        for k in used_leads:
            if k in self.by_key:
                used_business |= business_keys(self.by_key[k])
        for lead in sorted(self.leads, key=lambda ld: (0 if ld.opted_in else 1, ld.email_rank, self._score(ld))):
            if not any(v > 0 for v in left.values()):
                break
            if not lead.fresh or lead.key in used_leads or not (lead.emails or lead.unverified_emails):
                continue
            if not (manual or self._open_for(lead)):
                continue
            rule = PACKS[lead.country].rules.cold_email if lead.country in PACKS else "consent_only"
            if not lead.opted_in:
                if lead.objects_to_advertising:
                    continue            # its website says it does not want advertising
                if rule == "consent_only" or (rule == "companies_only" and not lead.is_company):
                    self.stats["not_emailed_by_rule"] += 1
                    continue
            keys = business_keys(lead)
            if keys & used_business or blocked(*[p for p, _ in lead.phones], *lead.whatsapp):
                continue
            guessed_ok = e["include_unverified"] and rule != "published_role"
            tried = False
            for addr in lead.emails + (lead.unverified_emails if guessed_ok else []):
                dom = email_domain(addr)
                if addr in used_emails or blocked(addr, "@" + dom):
                    continue
                if e["one_per_domain"] and dom not in FREE_MAIL and dom in used_domains:
                    continue
                tried = True
                verdict, why = self.verifier.check(addr)
                if verdict == "bad" or (verdict == "risky" and not e["send_risky"] and "could not be checked" not in why):
                    self.store.conn.execute("INSERT OR IGNORE INTO skipped(email, lead_key, reason, at) VALUES(?,?,?,?)",
                                            (addr, lead.key, why, now))
                    used_emails.add(addr)
                    self.stats["skipped"] += 1
                    continue
                box = max((b for b in left if left[b] > 0), key=lambda b: left[b])
                out.append(Item("new", 1, addr, lead, None, box))
                left[box] -= 1
                used_emails.add(addr)
                used_leads.add(lead.key)
                used_business |= keys
                if dom not in FREE_MAIL:
                    used_domains.add(dom)
                break
            else:
                if tried and self.live:
                    self._set_status(lead, STATUS_SKIPPED)     # every address it has was refused by the checker
        return out

    def _stub(self, t) -> Lead:
        market = self.markets.get(t["market"] or "")
        return Lead(key=t["lead_key"], lead_id=t["lead_id"] or "", business=t["business"] or "",
                    market=t["market"] or "", country=market.country if market else "US",
                    tz=market.tz_of(t["lead_id"] or "") if market else "")

    def _compose(self, item: Item):
        box = self._box(item.box)
        name = (box.name if box else "") or self.o["sender"]["name"]
        addr = box.address if box else item.box
        if item.kind == "new":
            subject, body = T.first_email(item.lead, self.o, mailbox_name=name)
            path = str(self.o["email"].get("attachment") or "")
            path = Path(path) if not path or Path(path).is_absolute() else ROOT / path
            attach = [(_pdf_name(self.o), path.read_bytes())] if str(path) and path.is_file() else None
            msg = build_message(sender_name=name, sender_addr=addr, to=item.email, subject=subject, body=body,
                                attachments=attach)
            if self.bcc:
                msg["Bcc"] = self.bcc
            return msg
        t = item.thread
        ids = self.store.msgids(t)
        subject = t["subject"] if (t["subject"] or "").lower().startswith("re:") else f"Re: {t['subject']}"
        return build_message(sender_name=name, sender_addr=addr, to=item.email, subject=subject,
                             body=T.follow_up(item.lead, self.o, item.step - 1, mailbox_name=name),
                             in_reply_to=ids[-1] if ids else "", references=ids)

    # ------------------------------------------------------------------ e-mail: sending
    def _send_all(self, items: list[Item]) -> None:
        """Every mailbox works through its own list, a few minutes between two of its e-mails; the mailboxes take
        turns, so three mailboxes send three times as much in the same hour."""
        e = self.o["email"]
        queues: dict[str, list[Item]] = {}
        for item in items:
            queues.setdefault(item.box, []).append(item)
        started = self.now()
        budget = float(e["run_budget_minutes"]) * 60
        lo, hi = float(e["min_gap_seconds"]), float(e["max_gap_seconds"])
        # each mailbox's list spread over nine tenths of the run's time (the rest is room for slow answers)
        even = {b: min(hi, max(lo, 0.9 * budget / max(1, len(q)))) for b, q in queues.items()}
        next_at = {b: started + i * lo / max(1, len(queues)) for i, b in enumerate(queues)}
        manual = self.max_emails is not None
        temp_failures: dict[str, int] = {}
        while any(queues.values()):
            box_key = min((b for b in queues if queues[b]), key=lambda b: next_at[b])
            wait = next_at[box_key] - self.now()
            if self.now() + max(0.0, wait) - started > budget:
                self.notes.append("run time used up - the rest goes out in the next run")
                break
            if wait > 0:
                self.sleep(wait)
            item = queues[box_key].pop(0)
            if not (manual or self._open_for(item.lead)):
                continue                # their office closed while this run was sending
            box = self._box(box_key)
            try:
                msg = self._compose(item)
                res = self._mailer(box).send(msg)
                tries = 0
                while res.status == "network" and tries < NETWORK_RETRIES and \
                        self.now() - started + NETWORK_RETRY_S <= budget:
                    tries += 1
                    self.sleep(NETWORK_RETRY_S)
                    res = self._mailer(box).send(msg)
            except Exception as exc:  # noqa: BLE001 - one odd lead must never stop the run
                self.notes.append(f"skipped {item.email}: {type(exc).__name__}: {exc}"[:200])
                continue
            self._record(item, msg, res)
            self.sent_log.append([item.lead.lead_id, item.lead.business, item.email, box.address, res.status,
                                  msg["Subject"]])
            next_at[box_key] = self.now() + max(lo, even[box_key] * self.rng.uniform(0.8, 1.2))
            if res.ok:
                temp_failures[box_key] = 0
            elif res.status == "limit":
                until = ramp.on_limit(self.store, self.o, box, self._day(), self.now(), f"{res.code} {res.detail}")
                self._paused(box, until)
                queues[box_key] = []
            elif res.status == "blocked":
                until = ramp.on_blocked(self.store, self.o, box, self._day(), self.now(), f"{res.code} {res.detail}")
                self._paused(box, until)
                queues[box_key] = []
            elif res.status == "auth":
                why = (f"{box.address}: the login stopped working ({res.detail[:120]}) - " +
                       (f"run  wr outlook-login {box.index}" if box.kind == "outlook" else
                        "make a new app password and put it in  wr settings"))
                self.notes.append(why)
                self.alerts.append(why)
                self.code = max(self.code, 2)
                queues[box_key] = []
            elif res.status == "network":
                self.notes.append(f"no internet connection to the mail server ({res.detail[:120]}) - trying again next run")
                self.code = max(self.code, 2)
                break
            elif res.status == "temp":
                temp_failures[box_key] = temp_failures.get(box_key, 0) + 1
                if temp_failures[box_key] >= 3:
                    self.notes.append(f"{box.address}: temporary problems ({res.detail[:120]}) - trying again next run")
                    queues[box_key] = []
        for box in self.usable:
            until = ramp.check_bounces(self.store, self.o, box, self._day(), self.now())
            if until:
                self._paused(box, until)

    def _paused(self, box, until: float) -> None:
        why = self.store.box(box.key).get("pause_reason", "")
        line = f"{box.address}: SENDING PAUSED until {fmt_local(self.o['email']['day_tz'], until)} - {why}"
        self.notes.append(line)
        self.alerts.append(line)
        self.code = max(self.code, 2)

    def _record(self, item: Item, msg, res) -> None:
        if res.status not in ("sent", "invalid"):
            return                      # nothing changed; the same e-mail is tried again in a later run
        now, day = self.now(), self._day()
        lead, addr = item.lead, item.email
        msgid = res.msgid or msg["Message-ID"]
        fu = self.o["email"]["follow_up_days"]
        with self.store.tx():
            self.store.conn.execute("INSERT INTO sends(email,lead_key,mailbox,step,msgid,sent_at,day,status,error) "
                                    "VALUES(?,?,?,?,?,?,?,?,?)",
                                    (addr, lead.key, item.box, item.step, msgid, now, day, res.status,
                                     res.detail[:300] if res.status != "sent" else None))
            if res.status == "invalid":
                self.store.suppress(addr, "email", f"rejected by the mail server ({res.code})", "bounce")
                if item.thread is None:
                    self.store.conn.execute(
                        "INSERT INTO threads(email,lead_key,lead_id,business,domain,market,mailbox,stage,step,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)", (addr, lead.key, lead.lead_id, lead.business, email_domain(addr),
                                                        lead.market, item.box, "bounced", 0, now))
                else:
                    self.store.conn.execute("UPDATE threads SET stage='bounced', next_due=NULL, updated_at=? WHERE email=?",
                                            (now, addr))
                self.stats["bounces"] += 1
                self._set_status(lead, STATUS_BOUNCED)
                return
            if item.thread is None:
                next_due = now + fu[0] * 86400 if fu else None
                self.store.conn.execute(
                    "INSERT INTO threads(email,lead_key,lead_id,business,domain,market,mailbox,stage,step,subject,msgids,"
                    "first_sent,last_sent,next_due,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (addr, lead.key, lead.lead_id, lead.business, email_domain(addr), lead.market, item.box,
                     "active" if fu else "completed", 1, msg["Subject"], jdump([msgid]), now, now, next_due, now))
                self.stats["new"] += 1
                self._set_status(lead, STATUS_EMAILED)
            else:
                t = item.thread
                step = t["step"] + 1
                ids = self.store.msgids(t) + [msgid]
                more = step - 1 < len(fu)        # follow-ups sent so far = step - 1
                next_due = (t["first_sent"] + fu[step - 1] * 86400) if more else None
                self.store.conn.execute("UPDATE threads SET step=?, msgids=?, last_sent=?, next_due=?, stage=?, updated_at=? "
                                        "WHERE email=?", (step, jdump(ids), now, next_due,
                                                          "active" if more else "completed", now, addr))
                self.stats["followups"] += 1
                self._set_status(lead, STATUS_FOLLOWUP.format(n=step - 1))

    def _send_test(self) -> None:
        """The spam test: the first e-mail the next business would get, sent from every mailbox only to the owner's
        test addresses. No business is e-mailed and nothing is recorded."""
        if not self.usable:
            self.notes.append("test: no mailbox is ready")
            self.code = 2
            return
        self.max_emails = len(self.usable)
        items = [i for i in self._pick({b.key: 1 for b in self.usable}) if i.kind == "new"]
        self.status_updates.clear()
        if not items:
            self.notes.append("test: no business left to take the e-mail's words from (run the lead search first)")
            self.code = 2
            return
        for n, box in enumerate(self.usable):
            item = items[n % len(items)]
            item = Item(item.kind, item.step, item.email, item.lead, None, box.key)
            if problem := self._mailer(box).check():
                self.notes.append(f"test: {problem}")
                self.code = 2
                continue
            msg = self._compose(item)
            for addr in self.test_to:
                del msg["To"]
                msg["To"] = addr
                res = self._mailer(box).send(msg)
                self.notes.append(f"test e-mail from {box.address} to {addr}: {res.status}"
                                  + (f" ({res.detail[:120]})" if not res.ok else "")
                                  + f' - subject "{msg["Subject"]}", written for {item.lead.business}')
                if not res.ok:
                    self.code = 2
            self._mailer(box).close()

    # ------------------------------------------------------------------ WhatsApp
    def _wa_row(self, lead: Lead, phone: str, reason: str) -> list:
        text = T.whatsapp_text(lead, self.o, reason)
        return [self._day(), lead.lead_id, lead.business, lead.category_label, lead.city or lead.area,
                display_phone(phone), REASONS[reason], text, wa_link(phone, text), "", lead.key]

    def _wa_cap(self) -> int:
        """A new number starts small and grows with the days messages really went out."""
        w = self.o["whatsapp"]
        days = len({r["day"] for r in self.store.q("SELECT day FROM wa_sent") if r["day"] and r["day"] < self._day()})
        return min(w["max_per_day"], w["start_per_day"] + w["step"] * (days // w["step_every_days"]))

    def _whatsapp_queue(self) -> None:
        """Today's cold WhatsApp messages: only numbers a business itself publishes as WhatsApp, only in countries
        whose rules allow a first message without consent, and only to businesses e-mail cannot reach (no address,
        or the e-mails got no answer). The owner sends each with one tap (WhatsApp bans numbers that automate)."""
        w = self.o["whatsapp"]
        if not w["enabled"] or not self.leads:
            return
        today, cap = self._day(), self._wa_cap()
        recent = datetime.fromtimestamp(self.now() - WA_STALE_DAYS * 86400, get_tz(self.o["email"]["day_tz"])).date().isoformat()
        pending = self.store.scalar("SELECT COUNT(*) FROM wa WHERE result='' AND reason!='opted_in' AND queued_day>=?",
                                    (recent,), 0)
        added_today = self.store.scalar("SELECT COUNT(*) FROM wa WHERE queued_day=? AND reason!='opted_in'", (today,), 0)
        room = max(0, min(cap - added_today, cap * max(1, int(w["max_waiting_days"])) - pending))
        if room == 0:
            return
        sup = self.store.suppressed_values()
        queued_phones = {r["phone"] for r in self.store.q("SELECT phone FROM wa")}
        queued_leads = {r["lead_key"] for r in self.store.q("SELECT DISTINCT lead_key FROM wa WHERE result!='not_on_whatsapp'")}
        emailing = {r["lead_key"] for r in self.store.q(
            "SELECT DISTINCT lead_key FROM threads WHERE stage IN ('active','replied','opted_out')")}
        ended = {r["lead_key"] for r in self.store.q(
            "SELECT DISTINCT lead_key FROM threads WHERE stage IN ('completed','no_reply','bounced')")}
        added = 0
        with self.store.tx():
            for lead in sorted(self.leads, key=self._score):
                if added >= room:
                    break
                if not lead.whatsapp or lead.country not in PACKS or \
                        PACKS[lead.country].rules.cold_whatsapp != "manual_queue":
                    continue
                if not lead.system_managed or lead.key in queued_leads or lead.key in emailing:
                    continue
                if lead.emails and lead.key not in ended:
                    continue            # e-mail reaches this business first
                if any(x.lower() in sup for x in lead.emails):
                    continue
                for phone in lead.whatsapp:
                    if phone in queued_phones or phone.lower() in sup:
                        continue
                    self.store.conn.execute("INSERT INTO wa(phone,lead_key,lead_id,business,reason,queued_day,result,updated_at) "
                                            "VALUES(?,?,?,?,?,?,?,?)", (phone, lead.key, lead.lead_id, lead.business, "listed",
                                                                        today, "", self.now()))
                    self.wa_rows.append(self._wa_row(lead, phone, "listed"))
                    queued_phones.add(phone)
                    queued_leads.add(lead.key)
                    added += 1
                    break
        self.stats["wa_queued"] += added

    # ------------------------------------------------------------------ the Sheet and the owner
    def _outreach_rows(self) -> list[list]:
        order = {"replied": 0, "opted_out": 1, "active": 2, "completed": 3, "no_reply": 4, "bounced": 5, "stopped": 6}
        tz = self.o["email"]["day_tz"]
        rows = []
        for t in sorted(self.store.q("SELECT * FROM threads"), key=lambda r: (order.get(r["stage"], 9), -(r["last_sent"] or 0))):
            lead = self.by_key.get(t["lead_key"])
            stage = {"active": "Waiting for reply", "replied": f"Replied ({REPLY_LABEL.get(t['reply_kind'] or '', 'reply')})",
                     "opted_out": "Opted out", "completed": "All e-mails sent", "no_reply": "No reply after follow-ups",
                     "bounced": "Bounced (bad address)", "stopped": "Stopped (owner took over or removed)"}.get(t["stage"], t["stage"])
            nums = (lead.whatsapp + [p for p, _ in lead.phones]) if lead else []
            market = self.markets.get(t["market"] or "")
            rows.append([t["lead_id"] or "", t["business"] or "", lead.category_label if lead else "",
                         lead.city if lead else "", market.country if market else "", t["email"], t["mailbox"] or "", stage,
                         t["step"], fmt_local(tz, t["last_sent"]), fmt_local(tz, t["next_due"]), t["reply_snippet"] or "",
                         display_phone(nums[0]) if nums else "", t["lead_key"]])
        return rows

    def _dashboard_rows(self) -> list[list]:
        """Everything at a glance, for the Dashboard tab (the owner reads it on the phone)."""
        e = self.o["email"]
        now, day, tz = self.now(), self._day(), e["day_tz"]
        india = datetime.fromtimestamp(now, get_tz("Asia/Kolkata")).strftime("%d %b %H:%M")
        rows = [["Last run", f"{india} India time", f"{fmt_local(tz, now)} New York time"],
                ["Mode", "LIVE - e-mails go out" if self.live else "DRY-RUN - nothing is sent",
                 "" if self.live else "LIVE=yes in the settings switches sending on"]]
        for box in self.boxes:
            d = ramp.describe(self.store, self.o, box, day, now)
            bad, sent = d["bounces"]
            cap = d["cap_today"] if d["cap_today"] is not None else d["steps"][min(d["step"], len(d["steps"])) - 1]
            problem = box.problem()
            state = (f"NOT SET UP: {problem}" if problem else
                     f"PAUSED until {fmt_local(tz, d['paused_until'])}" if d["paused_until"] else
                     f"sent {d['sent_today']} of {cap} today")
            details = (f"warm-up step {d['step']} of {len(d['steps'])}; last 24 hours {d['sent_24h']}"
                       + (f"; bounced {bad} of {sent} ({100 * bad / sent:.1f}%)" if sent else "")
                       + (f"; {d['pause_reason']}" if d["paused_until"] else ""))
            rows.append([f"Mailbox {box.index} ({box.kind}) {box.address}", state, details])
        t = {r["stage"]: r["n"] for r in self.store.q("SELECT stage, COUNT(*) AS n FROM threads GROUP BY stage")}
        r = {x["kind"]: x["n"] for x in self.store.q("SELECT kind, COUNT(*) AS n FROM replies GROUP BY kind")}
        due = self.store.scalar("SELECT COUNT(*) FROM threads WHERE stage='active' AND next_due<=?", (now,), 0)
        rows += [["Businesses written to", sum(t.values()), f"waiting for a reply {t.get('active', 0)}; no reply after "
                  f"all follow-ups {t.get('completed', 0) + t.get('no_reply', 0)}; bounced {t.get('bounced', 0)}"],
                 ["Replies", sum(r.get(k, 0) for k in ("positive", "other", "negative")),
                  f"interested {r.get('positive', 0)}; other {r.get('other', 0)}; not interested {r.get('negative', 0)}"],
                 ["Follow-ups due now", due, "they go out in the businesses' office hours"]]
        for m in self.markets.values():
            mine = [ld for ld in self.leads if ld.market == m.code]
            fresh = sum(1 for ld in mine if ld.fresh and ld.emails)
            rows.append([f"Businesses in {m.leads_tab}", len(mine), f"with an e-mail and not written to yet: {fresh}"])
        waiting = self.store.scalar("SELECT COUNT(*) FROM wa WHERE result=''", (), 0)
        open_replies = self.store.scalar("SELECT COUNT(*) FROM threads WHERE stage='replied'", (), 0)
        todo = []
        if open_replies:
            todo.append(f"answer the businesses that replied ({open_replies} in all, Replies tab)")
        if waiting:
            todo.append(f"send {waiting} WhatsApp message(s) (wr whatsapp)")
        if any(row[1].startswith(("PAUSED", "NOT SET UP")) for row in rows if str(row[0]).startswith("Mailbox")):
            todo.append("look at the mailbox marked PAUSED / NOT SET UP above")
        rows.append(["What to do now", "; ".join(todo) or "nothing - it is working by itself", ""])
        return rows

    def _write_sheet(self, sheet: OutreachSheet) -> None:
        tz = self.o["email"]["day_tz"]
        sheet.rewrite("dashboard", self._dashboard_rows())
        sheet.rewrite("outreach", self._outreach_rows())
        sheet.rewrite("preview", self.preview)
        if self.new_replies:
            rows = []
            for r in self.new_replies:
                lead = r["lead"]
                nums = (lead.whatsapp + [p for p, _ in lead.phones]) if lead else []
                chat = wa_link(nums[0], T.whatsapp_text(lead, self.o, "opted_in")) if r["kind"] == "positive" and nums else ""
                step = NEXT_STEP.get(r["kind"], "") + (" - the overview PDF was sent to them just now" if r["overview"] else "")
                rows.append([fmt_local(tz, self.now()), r["lead_id"] or "", r["business"] or "", r["email"],
                             display_phone(nums[0]) if nums else "", REPLY_LABEL.get(r["kind"], r["kind"]),
                             snippet(r["text"], 1000), step, chat, r["box"], r["lead_key"]])
            sheet.append("replies", rows)
        if self.wa_rows:
            sheet.append("whatsapp", self.wa_rows)
        new_dnc = self.store.q("SELECT * FROM suppression WHERE in_sheet=0 ORDER BY added_at")
        if new_dnc:
            sheet.append("dnc", [[r["value"], r["reason"] or "", fmt_local(tz, r["added_at"]), r["source"] or ""] for r in new_dnc])
            self.store.conn.execute("UPDATE suppression SET in_sheet=1 WHERE in_sheet=0")
        for code, statuses in self.status_updates.items():
            if code in self.markets:
                sheet.set_lead_statuses(self.markets[code].leads_tab, statuses)

    def _notify_owner(self) -> None:
        """One e-mail to the owner when a person answered or a mailbox stopped: these need them today."""
        hot = [r for r in self.new_replies if r["kind"] in ("positive", "other")]
        if not ((hot or self.alerts) and self.live and self.usable):
            return
        lines = []
        for r in hot:
            lead = r["lead"]
            nums = (lead.whatsapp + [p for p, _ in lead.phones]) if lead else []
            lines.append(f"- {r['business']} ({r['email']}) - {REPLY_LABEL.get(r['kind'])}, answered to {r['box']}\n"
                         f"  Phone: {display_phone(nums[0]) if nums else 'not listed'}\n"
                         f"  They wrote: {snippet(r['text'], 400)}"
                         + ("\n  The overview PDF went back to them automatically." if r["overview"] else ""))
        body = ""
        if lines:
            body += ("New replies from businesses. Answer them today, from the mailbox they wrote to: a reply within "
                     "the hour gets a call far more often.\n\n" + "\n\n".join(lines) + "\n\n")
        if self.alerts:
            body += "Needs your attention:\n" + "\n".join(f"- {a}" for a in self.alerts) + "\n\n"
        body += "All replies are in the Replies tab of the Google Sheet;  wr report  shows them on the tablet."
        subject = (f"{len(hot)} new {'reply' if len(hot) == 1 else 'replies'} from businesses" if hot else
                   "WorldReach: a mailbox needs your attention")
        for box in self.usable:
            if float(self.store.box(box.key).get("paused_until") or 0) > self.now():
                continue                # a paused mailbox sends nothing, not even this
            to = str(self.o["sender"].get("notify_email") or "").strip() or box.address
            res = self._mailer(box).send(build_message(sender_name="WorldReach", sender_addr=box.address, to=to,
                                                       subject=subject, body=body, unsubscribe=False))
            if res.ok:
                return
        self.notes.append("the alert e-mail to you could not be sent (see  wr report  for the replies)")

    # ------------------------------------------------------------------ report
    def _report_row(self) -> list:
        local = datetime.fromtimestamp(self.now(), get_tz(self.o["email"]["day_tz"]))
        s, day = self.stats, self._day()
        used = sum(self.store.sent_on(b.key, day) for b in self.boxes)
        return [day, local.strftime("%H:%M"), "live" if self.live else "dry-run", len(self.usable),
                sum(self.caps.values()), used, s["new"], s["followups"], s["positive"], s["negative"], s["other"],
                s["bounces"], s["skipped"], s["wa_queued"], "; ".join(self.notes)[:900]]

    def _summary(self, status: str) -> dict:
        n = self.stats["not_emailed_by_rule"]
        if n:
            note = (f"{n} business(es) not e-mailed because their country's rules ask for consent first "
                    "(UK and Ireland: only limited companies may be e-mailed cold; docs/COMPLIANCE.md)")
            if note not in self.notes:
                self.notes.append(note)
        return {"status": status, "mode": "live" if self.live else "dry-run", **self.stats,
                "limits_today": dict(self.caps), "notes": self.notes}


def overview_pdf(o: dict) -> Path | None:
    """The PDF for businesses that asked: the owner's own copy (with their phone and e-mail, put in place by
    wr pdf  as data/brochure.pdf) when there is one, else the one that comes with the code."""
    from ..settings import data_dir

    own = data_dir() / "brochure.pdf"
    if own.is_file():
        return own
    path = Path(str(o["auto_reply"].get("attachment") or ""))
    path = path if path.is_absolute() else ROOT / path
    return path if path.is_file() else None


def _pdf_name(o: dict) -> str:
    brand = re.sub(r"[^A-Za-z0-9]+", "-", str(o["sender"].get("business") or "")).strip("-")
    return f"{brand}-overview.pdf" if brand else "overview.pdf"
