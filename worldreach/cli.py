"""The commands ( wr COMMAND  on the tablet;  python -m worldreach COMMAND  anywhere).

    check                 are the settings, the Sheet and every mailbox right? are our own e-mails clean?
    preview               the e-mails each kind of business would get, with the text check (needs nothing set up)
    emails                one outreach run: replies, follow-ups, new e-mails (the robot does this every hour)
    emails --dry-run      prepare them into the Sheet's "Email Preview" tab, send nothing
    emails --max 2 --copy-to me@x.com   two real e-mails now, with a blind copy to you
    emails --check        only read replies and bounces
    test A@x.com B@y.com  the spam test: the next first e-mail from every mailbox, only to your own addresses
    leads                 find businesses in the next city, then hunt for missing e-mail addresses
    hunt                  more e-mail hunting in cities searched before
    status                mailboxes (warm-up, pauses), leads per city, e-mails and replies
    report                e-mails per day, bounces, replies, and who is waiting for your answer
    resume                end a sending pause now
    outlook-login N       sign mailbox N (an Outlook address) in, once
    dns DOMAIN            is a sending domain set up for delivery (SPF, DKIM, DMARC)?
    whatsapp ...          the WhatsApp queue for the tablet (list | next | mark | test)
    client ...            the follow-ups we run for a client (new | list | preview | run | report | stop)
    brochure              build marketing/brochure.pdf again (after changing marketing/brochure.json)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import settings as S
from .outreach import config as C

try:
    import fcntl
except ImportError:  # Windows: two runs at once are simply not prevented
    fcntl = None

ROOT = S.ROOT
BUSY = 3
TITLES = {"leads": "lead search", "hunt": "e-mail hunt", "emails": "e-mail sending"}
LEADS_SQL = "qualified=1 AND excluded IS NULL AND merged_into IS NULL"


class Busy(Exception):
    pass


@contextmanager
def job_lock(what: str):
    """One lead search or e-mail run at a time (the robot and commands typed by hand share this lock)."""
    data = S.data_dir()
    data.mkdir(parents=True, exist_ok=True)
    fh = open(data / "job.lock", "a+")
    if fcntl is not None:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.seek(0)
            holder = fh.read().strip() or "another job"
            fh.close()
            raise Busy(holder) from None
    fh.seek(0)
    fh.truncate()
    who = "the robot" if os.environ.get("WR_ROBOT_JOB") else "typed by hand"
    fh.write(f"{TITLES.get(what, what)} ({who}, since {datetime.now():%H:%M})")
    fh.flush()
    try:
        yield
    finally:
        fh.seek(0)
        fh.truncate()
        fh.close()


def outreach_db() -> Path:
    return S.data_dir() / "outreach.sqlite"


def open_store():
    from .outreach.store import Store

    return Store(str(outreach_db()))


def city_db(code: str, city: str) -> Path:
    return S.data_dir() / f"{code}-{city}.sqlite"


def load_all(need_markets: bool = True):
    settings = S.load()
    S.export(settings)
    o = C.load(settings=settings)
    markets = C.load_markets(o["markets"]) if need_markets else []
    return settings, o, markets


# ---------------------------------------------------------------------------------------------------- check / preview
def sample_leads(markets) -> list:
    """One made-up business per kind and country, to show and check our own words."""
    from .outreach.leads import Lead

    out = []
    names = {"gym": "Iron Temple Fitness", "studio": "Lotus Yoga Studio", "martial_arts": "Tiger Karate Academy",
             "salon": "Maple Street Salon", "spa": "Stillwater Day Spa", "hotel": "The Harbour Inn",
             "pets": "Happy Paws Grooming", "auto": "Westside Auto Repair", "restaurant": "Olive & Thyme",
             "cafe": "Daily Grind Cafe", "bar": "The Copper Tap"}
    for m in markets:
        city, tz = next(iter(m.cities.values()))
        for i, c in enumerate(m.categories):
            out.append(Lead(key=f"sample-{m.code}-{c['key']}", lead_id=f"{next(iter(m.cities))}-{i + 1}",
                            business=names.get(c["key"], "Sample Business"), category_key=c["key"],
                            category_label=c.get("label", ""), emails=["owner@example.com"], market=m.code,
                            country=m.country, tz=tz, city=city, person="Sam Carter" if i % 2 else "",
                            legal_form="Ltd/LLP/PLC"))
    return out


def text_problems(o: dict, markets) -> list[str]:
    """Every e-mail we could send, for every kind of business: what a spam filter would mind."""
    from .mail.lint import lint
    from .outreach import templates as T

    out = []
    for lead in sample_leads(markets):
        ctx = T.context(lead, o)
        subject, body = T.first_email(lead, o)
        texts = [("first e-mail", subject, body, False)]
        texts += [(f"follow-up {n}", "Re: " + subject, T.follow_up(lead, o, n), True)
                  for n in range(1, len(o["email"]["follow_up_days"]) + 1)]
        for what, subj, text, fu in texts:
            for problem in lint(subj.replace("Re: ", ""), text, footer=ctx["footer"], follow_up=fu):
                out.append(f"{what} for a {lead.category_label or lead.category_key} ({lead.country}): {problem}")
    return sorted(set(out))


def cmd_preview(a) -> int:
    from .outreach import templates as T

    settings = S.load()
    o = C.load(settings=settings)
    markets = C.load_markets(o["markets"])
    if not o["sender"]["name"]:
        o["sender"] = {**o["sender"], "name": "Your Name", "phone": "+00 0000 000000",
                       "postal_address": "Your street, your city, your country"}
    shown = 0
    for lead in sample_leads(markets[:1] if not a.all else markets):
        if a.kind and a.kind not in lead.category_key:
            continue
        subject, body = T.first_email(lead, o)
        print("=" * 78 + f"\n{lead.category_label}  ({lead.country})\nSubject: {subject}\n\n{body}\n")
        for n in range(1, len(o["email"]["follow_up_days"]) + 1):
            print(f"--- follow-up {n}, {o['email']['follow_up_days'][n - 1]} days after the first e-mail ---\n"
                  f"{T.follow_up(lead, o, n)}\n")
        shown += 1
    problems = text_problems(o, markets)
    print("=" * 78 + f"\n{shown} kind(s) of business shown. Text check: " +
          ("all clean (no links, no spam-filter words, short enough)." if not problems else ""))
    for p in problems:
        print("  ! " + p)
    return 1 if problems else 0


def cmd_check(_a) -> int:
    from .mail import open_mailbox

    ok = True

    def line(good: bool, text: str, warn: bool = False) -> None:
        nonlocal ok
        ok = ok and (good or warn)
        print(f"[{'OK' if good else ('!!' if not warn else '..')}] {text}")

    try:
        settings, o, markets = load_all()
    except (C.OutreachConfigError, Exception) as exc:  # noqa: BLE001 - say what is wrong with the files
        print(f"[!!] the configuration could not be read: {exc}")
        return 1
    s = o["sender"]
    line(bool(s["name"] and s["business"]), f"sender: {s['name'] or 'SENDER_NAME missing'}, {s['business'] or 'SENDER_BUSINESS missing'}")
    line(bool(s["postal_address"]), "postal address " + ("set" if s["postal_address"] else
         "missing (POSTAL_ADDRESS): US and Canadian law require it in every sales e-mail"))
    line(bool(s["phone"]), "WhatsApp / phone " + ("set" if s["phone"] else "not set (SENDER_PHONE): the e-mails then show none"),
         warn=True)
    print(f"     markets: {', '.join(f'{m.name} ({len(m.cities)} cities)' for m in markets)};  "
          f"mode: {'LIVE' if o['mode'] == 'live' else 'dry-run (LIVE=yes in settings switches sending on)'}")
    sheet_id = settings.get("WR_SHEET_ID", "")
    if not sheet_id:
        line(False, "Google Sheet: WR_SHEET_ID missing")
    elif not os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE"):
        line(False, "Google key file: none in the secrets folder (wr getkey)")
    else:
        try:
            from leadgen.sheets import SheetsClient

            tabs = SheetsClient(sheet_id).tabs()
            line(True, f"Google Sheet reachable ({len(tabs)} tabs)")
        except Exception as exc:  # noqa: BLE001
            line(False, f"Google Sheet: {str(exc)[:300]}")
    boxes = S.mailboxes(settings)
    line(bool(boxes), f"{len(boxes)} mailbox(es) in the settings" if boxes else "no mailbox in the settings (MAILBOX_1=gmail ...)")
    for box in boxes:
        problem = box.problem() or open_mailbox(box).check()
        line(not problem, f"mailbox {box.index} ({box.kind}) {box.address}: " + (problem or "login OK"))
        if not problem and box.kind == "smtp":
            try:
                from .mail.dnscheck import check_domain

                for what, good, detail in check_domain(box.domain):
                    line(good, f"   {box.domain} {what}: {detail}", warn=True)
            except Exception as exc:  # noqa: BLE001 - no DNS now: not a reason to fail the check
                print(f"     ({box.domain}: DNS could not be checked now: {exc})")
    problems = text_problems(o, markets)
    line(not problems, "our e-mails: " + ("clean (no links, no spam-filter words, short enough)" if not problems
                                          else f"{len(problems)} thing(s) a spam filter would mind:"))
    for p in problems[:12]:
        print("       " + p)
    pdf = ROOT / str(o["auto_reply"]["attachment"])
    line(pdf.is_file(), f"overview PDF for interested businesses: {pdf.name}" + ("" if pdf.is_file() else " is missing"),
         warn=True)
    print("\nAll good." if ok else "\nFix the lines marked [!!] (wr settings), then run  wr check  again.")
    return 0 if ok else 1


# ---------------------------------------------------------------------------------------------------- e-mails
def cmd_emails(a) -> int:
    from .outreach.engine import Engine

    settings, o, markets = load_all()
    live = None if not a.dry_run else False
    max_emails = 0 if a.check else a.max
    store = open_store()
    try:
        eng = Engine(o, store, S.mailboxes(settings), markets, sheet_id=settings.get("WR_SHEET_ID", ""), live=live,
                     max_emails=max_emails, bcc=a.copy_to, only_box=a.box, test_to=getattr(a, "test_to", ()))
        code, summary = eng.run()
    finally:
        store.close()
    print_summary(summary, eng.sent_log)
    return code


def print_summary(summary: dict, sent_log: list) -> None:
    s = summary
    print(f"Outreach run ({s['mode']}): {s['status']}")
    print(f"  new e-mails {s['new']}, follow-ups {s['followups']}, overviews sent {s['overviews']}, prepared (dry-run) {s['planned']}")
    print(f"  replies: interested {s['positive']}, other {s['other']}, not interested {s['negative']};  bounces {s['bounces']};  "
          f"addresses refused by the checker {s['skipped']};  WhatsApp queued {s['wa_queued']}")
    if s.get("limits_today"):
        print("  today's limits: " + ", ".join(f"{k} {v}" for k, v in s["limits_today"].items()))
    for n in s.get("notes") or []:
        print(f"  note: {n}")
    for lead_id, business, to, box, result, subject in sent_log[:200]:
        print(f"    {lead_id:<9} {business[:30]:<31} -> {to}  [{result}] from {box}  \"{subject}\"")


def cmd_test(a) -> int:
    a.dry_run, a.check, a.max, a.copy_to = False, False, None, ""
    with_live = argparse.Namespace(**{**vars(a), "test_to": a.addresses})
    settings, o, markets = load_all()
    from .outreach.engine import Engine

    store = open_store()
    try:
        eng = Engine(o, store, S.mailboxes(settings), markets, sheet_id=settings.get("WR_SHEET_ID", ""), live=True,
                     only_box=with_live.box, test_to=a.addresses)
        code, summary = eng.run()
    finally:
        store.close()
    for n in summary["notes"]:
        print(n)
    print("\nNow open each test mailbox and look where the e-mail from each of your mailboxes landed: Primary, "
          "Promotions, Updates or Spam. An address from mail-tester.com gives a score out of 10 as well "
          "(docs/DELIVERABILITY.md).")
    return code


def cmd_resume(_a) -> int:
    from .outreach import ramp

    settings = S.load()
    store = open_store()
    try:
        lines = [f"{b.address}: pause ended ({why})" for b in S.mailboxes(settings)
                 if (why := ramp.resume(store, b.key, time.time()))]
    finally:
        store.close()
    print("\n".join(lines) if lines else "No mailbox is paused: nothing to do.")
    return 0


def cmd_outlook_login(a) -> int:
    from .mail.outlook import GraphMailbox, LoginNeeded

    settings = S.load()
    box = next((b for b in S.mailboxes(settings) if b.index == a.n), None)
    if box is None or box.kind != "outlook":
        print(f"Mailbox {a.n} is not an Outlook mailbox in settings.txt (MAILBOX_{a.n}=outlook, MAILBOX_{a.n}_ADDRESS=...).")
        return 2
    if box.problem():
        print(box.problem())
        return 2
    mb = GraphMailbox(box.address, box.client_id, tenant=box.tenant, index=box.index)
    try:
        flow = mb.start_login()
        print(f"\n1. Open this page in your browser:   {flow.get('verification_uri', 'https://microsoft.com/devicelogin')}\n"
              f"2. Type this code:                   {flow.get('user_code')}\n"
              f"3. Sign in as {box.address} and tap Accept.\n\nWaiting for you to finish (up to 15 minutes)...", flush=True)
        mb.finish_login(flow)
    except LoginNeeded as exc:
        print(f"\n{exc}")
        return 1
    problem = mb.check()
    print(f"\n{problem}" if problem else f"\nSigned in. {box.address} can send and read its replies now.")
    return 1 if problem else 0


def cmd_dns(a) -> int:
    from .mail.dnscheck import check_domain

    bad = 0
    for what, good, detail in check_domain(a.domain):
        print(f"[{'OK' if good else '!!'}] {what}: {detail}")
        bad += not good
    return 1 if bad else 0


# ---------------------------------------------------------------------------------------------------- leads
def city_order(codes: list[str]) -> list[tuple[str, str]]:
    """(market, city) in the order they are searched: the first city of every market, then the second of each ..."""
    fleets = {c: C.fleet(c) for c in codes}
    out = []
    for i in range(max((len(f) for f in fleets.values()), default=0)):
        out += [(c, fleets[c][i]) for c in codes if i < len(fleets[c])]
    return out


def next_cities(codes: list[str], n: int = 1) -> list[tuple[str, str]]:
    """A city whose search is under way first (it is finished before another starts), then cities never searched,
    then the one searched longest ago."""
    from leadgen.progress import city_progress

    order = city_order(codes)

    def rank(item: tuple[int, tuple[str, str]]) -> tuple:
        i, (code, city) = item
        db = city_db(code, city)
        if not db.exists():
            return (1, 0.0, i)
        state = city_progress(db)
        return (0, 0.0, i) if state and state["unfinished"] else (2, db.stat().st_mtime, i)
    return [x for _, x in sorted(enumerate(order), key=rank)][:n]


def leadgen(*args: str) -> int:
    cmd = [sys.executable, "-m", "leadgen", *args]
    print("\n>>> leadgen " + " ".join(args), flush=True)
    return subprocess.call(cmd, cwd=ROOT, env=os.environ.copy())


def cmd_leads(a) -> int:
    settings, o, _ = load_all(need_markets=False)
    if a.city:
        code, _, city = a.city.partition("/")
        wanted = [(code, city)] if city else [(m, a.city) for m in o["markets"] if a.city in C.fleet(m)][:1]
        if not wanted or wanted[0][1] not in C.fleet(wanted[0][0]):
            print(f"Unknown city {a.city!r}. Write it as  us/austin  or  gb/manchester  (see config/<market>/fleet.toml).")
            return 2
    else:
        wanted = next_cities(o["markets"], a.count)
    worst = 0
    for code, city in wanted:
        print(f"City: {city} ({code}) - {a.minutes:.0f} min search + {a.hunt_minutes:.0f} min e-mail hunt")
        common = ["--config", f"config/{code}/{city}.toml", "--db", str(city_db(code, city))]
        worst = max(worst, leadgen("run", *common, "--budget-minutes", str(a.minutes)))
        if a.hunt_minutes > 0:
            worst = max(worst, leadgen("email-hunt", *common, "--limit", "1500", "--budget-minutes", str(a.hunt_minutes)))
    print("\nDone. The new businesses are in your Google Sheet (the Leads tabs).")
    return worst


def not_yet_hunted(db: Path) -> int:
    from leadgen.hunt import HUNT_VERSION

    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return con.execute(
                f"SELECT COUNT(*) FROM places WHERE {LEADS_SQL} AND key NOT IN (SELECT place_key FROM contacts WHERE "
                "kind='email' AND confidence!='low') AND key NOT IN (SELECT place_key FROM tasks WHERE kind='hunt' "
                "AND key LIKE ?)", (f"hunt:{HUNT_VERSION}:%",)).fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def cmd_hunt(a) -> int:
    _settings, o, _ = load_all(need_markets=False)
    todo = sorted(((not_yet_hunted(city_db(c, city)), c, city) for c, city in city_order(o["markets"])
                   if city_db(c, city).exists()), reverse=True)
    todo = [t for t in todo if t[0]]
    if not todo:
        print("Every business found so far has been looked at by the e-mail hunt.")
        return 0
    end, worst = time.time() + a.minutes * 60, 0
    for n, code, city in todo:
        left = (end - time.time()) / 60
        if left < 5:
            break
        minutes = min(left, max(15.0, a.minutes / 2))
        print(f"\n{city} ({code}): {n} businesses without an e-mail not looked at yet ({minutes:.0f} min)")
        worst = max(worst, leadgen("email-hunt", "--config", f"config/{code}/{city}.toml", "--db", str(city_db(code, city)),
                                   "--limit", "1500", "--budget-minutes", f"{minutes:.0f}"))
    return worst


def lead_counts(codes: list[str]) -> list[tuple[str, str, int, int, int]]:
    """(market, city, businesses, with e-mail, searched %) per city searched so far."""
    from leadgen.progress import city_progress

    sql = ("SELECT COUNT(*), SUM(EXISTS(SELECT 1 FROM contacts c WHERE c.place_key=p.key AND c.kind='email' AND "
           "c.confidence!='low')) FROM places p WHERE p.qualified=1 AND p.excluded IS NULL AND p.merged_into IS NULL")
    out = []
    for code, city in city_order(codes):
        db = city_db(code, city)
        if not db.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            n, e = con.execute(sql).fetchone()
            con.close()
        except sqlite3.Error:
            continue
        state = city_progress(db) or {}
        out.append((code, city, n or 0, e or 0, state.get("searched_pct", 0)))
    return out


# ---------------------------------------------------------------------------------------------------- status / report
def status_text(now: float | None = None) -> str:
    from .outreach import ramp
    from leadgen.util import fmt_local, get_tz

    now = time.time() if now is None else now
    settings = S.load()
    o = C.load(settings=settings)
    tz = o["email"]["day_tz"]
    day = datetime.fromtimestamp(now, get_tz(tz)).date().isoformat()
    lines = [f"Mode: {'LIVE - e-mails go out' if o['mode'] == 'live' else 'dry-run - nothing is sent (LIVE=yes in  wr settings  switches it on)'}"
             + ("" if o["email"]["enabled"] else "   [e-mail sending switched off in config/outreach.toml]"),
             f"Markets: {', '.join(o['markets'])}", "", "Mailboxes:"]
    boxes = S.mailboxes(settings)
    if not outreach_db().exists():
        lines.append("  (no e-mail sent yet)" if boxes else "  none in the settings yet (wr settings)")
        boxes_done = True
    else:
        boxes_done = False
    store = None if boxes_done else open_store()
    try:
        for box in ([] if store is None else boxes):
            d = ramp.describe(store, o, box, day, now)
            bad, sent = d["bounces"]
            cap = d["cap_today"] if d["cap_today"] is not None else d["steps"][min(d["step"], len(d["steps"])) - 1]
            line = (f"  {box.index}. {box.address} ({box.kind}): warm-up day-step {d['step']} of {len(d['steps'])}, today "
                    f"{d['sent_today']} of {cap}, last 24 hours {d['sent_24h']}"
                    + (f", bounces {bad} of {sent} ({100 * bad / sent:.1f}%)" if sent else ""))
            if d["ceiling"]:
                line += f", held under {d['ceiling']} a day for now"
            lines.append(line)
            if d["paused_until"]:
                lines.append(f"     SENDING PAUSED until {fmt_local(tz, d['paused_until'])} ({tz}): {d['pause_reason']}"
                             "   ( wr resume  ends it now)")
        if store is not None:
            t = {r["stage"]: r["n"] for r in store.q("SELECT stage, COUNT(*) AS n FROM threads GROUP BY stage")}
            total = sum(t.values())
            r = {x["kind"]: x["n"] for x in store.q("SELECT kind, COUNT(*) AS n FROM replies GROUP BY kind")}
            fu = store.scalar("SELECT COUNT(*) FROM sends WHERE step>1 AND status='sent'", (), 0)
            due = store.scalar("SELECT COUNT(*) FROM threads WHERE stage='active' AND next_due<=?", (now,), 0)
            lines += ["", f"E-mails so far: {total} businesses written to, {fu} follow-ups sent, {due} follow-up(s) due now",
                      f"  waiting for a reply {t.get('active', 0)}, no reply after all follow-ups "
                      f"{t.get('completed', 0) + t.get('no_reply', 0)}, bounced {t.get('bounced', 0)}",
                      f"  replies: interested {r.get('positive', 0)}, other {r.get('other', 0)}, not interested "
                      f"{r.get('negative', 0)}   ( wr report  lists them)"]
            wa = store.scalar("SELECT COUNT(*) FROM wa WHERE result=''", (), 0)
            if wa:
                lines.append(f"  WhatsApp messages waiting for your tap: {wa}   ( wr whatsapp )")
    finally:
        if store is not None:
            store.close()
    counts = lead_counts(o["markets"])
    lines += ["", "Businesses found (with an e-mail address / all), per city:"]
    if not counts:
        lines.append("  none yet - the lead search runs once a day ( wr leads  runs it now)")
    for code, city, n, e, pct in counts:
        lines.append(f"  {code}/{city:<16} {e:>6} / {n:<6}  searched {pct}%")
    if counts:
        lines.append(f"  total: {sum(c[3] for c in counts)} with an e-mail address")
    nxt = next_cities(o["markets"], 1)
    if nxt:
        lines.append(f"  next lead search: {nxt[0][0]}/{nxt[0][1]}")
    return "\n".join(lines)


def cmd_status(_a) -> int:
    print(status_text())
    return 0


def report_data(store, days: int, tz: str, now: float) -> dict:
    from leadgen.util import get_tz

    zone = get_tz(tz)
    per_day: dict[str, dict] = {}
    blank = lambda: {"first": 0, "followup": 0, "bounced": 0, "positive": 0, "other": 0, "negative": 0}  # noqa: E731
    for r in store.q("SELECT day, step, status FROM sends"):
        d = per_day.setdefault(r["day"], blank())
        if r["status"] in ("sent", "invalid") and r["step"] >= 1:
            d["first" if r["step"] == 1 else "followup"] += 1
        if r["status"] in ("invalid", "bounced"):
            d["bounced"] += 1
    names = {r["email"]: r for r in store.q("SELECT email, business, lead_id, mailbox, auto_replied FROM threads")}
    replies = []
    for r in store.q("SELECT email, kind, received_at, snippet, mailbox FROM replies ORDER BY received_at"):
        if r["kind"] not in ("positive", "other", "negative"):
            continue
        local = datetime.fromtimestamp(r["received_at"], zone)
        per_day.setdefault(local.date().isoformat(), blank())[r["kind"]] += 1
        t = names.get(r["email"])
        replies.append({"at": local.strftime("%Y-%m-%d %H:%M"), "kind": r["kind"], "email": r["email"],
                        "business": t["business"] if t else "", "lead_id": t["lead_id"] if t else "",
                        "mailbox": r["mailbox"] or (t["mailbox"] if t else ""), "text": " ".join(str(r["snippet"] or "").split()),
                        "overview": bool(t and t["auto_replied"])})
    first = datetime.fromtimestamp(now - (max(1, days) - 1) * 86400, zone).date().isoformat()
    total = blank()
    for v in per_day.values():
        for k in total:
            total[k] += v[k]
    return {"days": {d: v for d, v in sorted(per_day.items()) if d >= first}, "total": total, "replies": replies}


def cmd_report(a) -> int:
    settings = S.load()
    o = C.load(settings=settings)
    if not outreach_db().exists():
        print("No e-mail has been sent yet.")
        return 0
    store = open_store()
    try:
        r = report_data(store, a.days, o["email"]["day_tz"], time.time())
    finally:
        store.close()
    widths = (10, 5, 5, 9, 7, 7, 10, 5, 3)
    row = lambda c: "  ".join(f"{x:>{w}}" if j else f"{x:<{w}}" for j, (x, w) in enumerate(zip(c, widths)))  # noqa: E731

    def cells(label, v):
        return [label, v["first"] + v["followup"], v["first"], v["followup"], v["bounced"],
                v["positive"] + v["other"] + v["negative"], v["positive"], v["other"], v["negative"]]
    print(f"E-mails per day, all mailboxes together (last {a.days} days). Opens cannot be counted: the e-mails carry "
          "no tracking pixel, which would send them to spam.\n")
    print(row(["Date", "Sent", "First", "Follow-up", "Bounced", "Replies", "Interested", "Other", "No"]))
    for day, v in r["days"].items():
        print(row(cells(day, v)))
    print(row(cells("All days", r["total"])))
    t = r["total"]
    sent = t["first"]
    if sent:
        print(f"\nOf {sent} businesses written to: {100 * (t['positive'] + t['other'] + t['negative']) / sent:.1f}% replied, "
              f"{100 * t['positive'] / sent:.1f}% interested; {100 * t['bounced'] / max(1, sent + t['followup']):.1f}% of all e-mails bounced.")
    latest: dict[str, dict] = {}
    for x in r["replies"]:
        latest[x["email"]] = x
    for kind, title in (("positive", "Interested - answer these first"), ("other", "Other replies - read and answer"),
                        ("negative", "Not interested - removed, nothing to do")):
        items = [x for x in latest.values() if x["kind"] == kind]
        if kind == "negative" and not a.all:
            print(f"\n{title}: {len(items)}")
            continue
        print(f"\n{title} ({len(items)}):" + ("" if items else " none"))
        for x in reversed(items[-a.limit:]):
            print(f"  {x['email']}   {x['business']} {x['lead_id']}   {x['at']}, to {x['mailbox']}"
                  + ("   [overview PDF sent automatically]" if x["overview"] else ""))
            print(f"      \"{x['text'][:200]}\"")
    print("\nAnswer from the mailbox shown after \"to\". The Replies tab of the Sheet has the same list with phone numbers.")
    return 0


# ---------------------------------------------------------------------------------------------------- WhatsApp
def cmd_whatsapp(a) -> int:
    """The WhatsApp Queue for android/whatsapp.sh. Sends nothing: the owner presses Send in WhatsApp Business."""
    from leadgen.sheets import SheetsClient

    from .outreach import wa_queue
    from .outreach.whatsapp import REASONS, wa_link

    settings, o, _ = load_all(need_markets=False)
    tab = o["tabs"]["whatsapp"]
    out = lambda *fields: print("\t".join(" ".join(str(f).split()) or "-" for f in fields))  # noqa: E731
    try:
        client = SheetsClient(settings.get("WR_SHEET_ID", ""))
        if a.action == "test":
            import phonenumbers

            try:
                num = phonenumbers.parse(a.number, "US")
                number = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164) \
                    if phonenumbers.is_valid_number(num) else ""
            except phonenumbers.NumberParseException:
                number = ""
            if not number:
                print(f"{a.number!r} is not a phone number: type it with the country code, like +1 512 555 0100.")
                return 2
            n = len(wa_queue.pending(client, tab))
            text = (f"Test message from {o['sender']['business']}: the WhatsApp queue on our tablet is connected "
                    f"({n} message{'' if n == 1 else 's'} waiting). No need to reply.")
            out(0, "-", number, "-", "Test message", wa_link(number, text))
            return 0
        if a.action == "mark":
            row = wa_queue.mark(client, tab, a.row, "" if a.key == "-" else a.key, a.number, a.result)
            print(f"Saved: {a.result}" if row else "That message is no longer in the WhatsApp Queue tab - nothing saved.")
            return 0 if row else 1
        items = wa_queue.pending(client, tab)
        items.sort(key=lambda it: (it["why"] != REASONS["opted_in"], it["date"] or "9999"))
        if a.action == "next":
            digits = lambda n: "".join(ch for ch in str(n) if ch.isdigit())  # noqa: E731
            skip = {digits(n) for n in (a.skip or [])}
            items = [it for it in items if digits(it["number"]) not in skip]
            if items:
                it = items[0]
                out(*(it[k] for k in ("row", "key", "number", "lead_id", "business", "link")))
            return 0
        print(f"WhatsApp Queue: {len(items)} message{'' if len(items) == 1 else 's'} to send.")
        for it in items[:20]:
            print(f"  {it['lead_id']:<10} {it['business'][:34]:<35} {it['number']:<18} {it['why']}")
        return 0
    except Exception as exc:  # noqa: BLE001 - the tablet's loop must go on; nothing is lost
        print(f"The Google Sheet did not answer ({type(exc).__name__}: {str(exc)[:150]}). Nothing is lost - try again "
              "in a minute.")
        return 5


# ---------------------------------------------------------------------------------------------------- clients
def clients_dir() -> Path:
    return Path(os.environ.get("WR_CLIENTS_DIR") or ROOT / "clients-data")


def cmd_client(a) -> int:
    """The service we sell, run for a client (worldreach/clients/)."""
    from .clients.campaigns import CLIENT_TOML, Client, ClientError
    from .mail import open_mailbox

    base = clients_dir()
    if a.action == "new":
        folder = base / a.id
        if (folder / "client.toml").exists():
            print(f"{folder} exists already.")
            return 1
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "client.toml").write_text(CLIENT_TOML.replace("{id}", a.id), encoding="utf-8")
        print(f"Made {folder}/client.toml - fill it in, save the client's export as {folder}/customers.csv,\n"
              f"then:  wr client preview {a.id}")
        return 0
    if a.action == "list" or (a.action == "run" and a.all):
        ids = sorted(p.parent.name for p in base.glob("*/client.toml"))
        if a.action == "list":
            print("\n".join(ids) if ids else "No clients yet ( wr client new NAME ).")
            return 0
    else:
        ids = [a.id]
    if not ids or ids == [None]:
        print("Which client? ( wr client list )" if a.action != "run" else "No clients yet.")
        return 0 if a.action == "run" else 2
    settings = S.load()
    boxes = {b.index: b for b in S.mailboxes(settings)}
    worst = 0
    for cid in ids:
        try:
            client = Client(base / cid)
        except ClientError as exc:
            print(exc)
            worst = 1
            continue
        try:
            if a.action == "stop":
                print("Stopped: never written to again." if client.stop(a.email, "stopped by hand") else "Was stopped already.")
            elif a.action == "report":
                print_client_report(client.report(a.days))
            elif a.action == "preview":
                problems = client.problems()
                due = client.due_today() if not any("customers.csv" in p for p in problems) else []
                print(f"{client.cfg['name'] or cid}: {len(client.customers())} customers in the list, "
                      f"{len(due)} message(s) due today.")
                for p in problems:
                    print(f"  ! {p}")
                shown = set()
                for d in due:
                    if (d.campaign, d.step) in shown:
                        continue
                    shown.add((d.campaign, d.step))
                    n = sum(1 for x in due if (x.campaign, x.step) == (d.campaign, d.step))
                    print(f"\n--- {d.campaign} {d.step}: {n} customer(s), e.g. to {d.customer.email} ---\n"
                          f"Subject: {d.subject}\n\n{d.body}")
                if not client.cfg["approved"]:
                    print("\nNothing is sent until client.toml says  approved = true .")
                worst = max(worst, 1 if problems else 0)
            else:                       # run
                problems = client.problems()
                box = boxes.get(int(client.cfg["mailbox"]))
                if problems or box is None or box.problem():
                    print(f"{cid}: not run - " + "; ".join(problems or [f"mailbox {client.cfg['mailbox']} is not set up"]))
                    worst = max(worst, 1)
                    continue
                stats = client.run(open_mailbox(box), live=not a.dry_run)
                print(f"{cid}: due {stats['due']}, sent {stats['sent']}, failed {stats['failed']}, answers "
                      f"{stats['replies']}, stops {stats['stops']}" + (f" - {stats['note']}" if stats["note"] else ""))
        except ClientError as exc:
            print(f"{cid}: {exc}")
            worst = 1
        finally:
            client.close()
    return worst


def print_client_report(r: dict) -> None:
    m = r["messages"]
    print(f"{r['client']}: the last {r['days']} days\n"
          f"  messages sent: {sum(m.values())} to {r['people']} customers  (review requests {m.get('review', 0)}, "
          f"come-back reminders {m.get('comeback', 0)}, win-back notes {m.get('winback', 0)}, payment reminders "
          f"{m.get('payment', 0)})\n"
          f"  came back after a note: {len(r['returns'])}    answers: {len(r['replies'])}    asked to stop: {r['stops']}")
    for x in r["returns"][-30:]:
        print(f"    back: {x['email']}  (visit {x['visit']}, after a {x['after']} note)")
    for x in r["replies"][-30:]:
        print(f"    answer from {x['email']}: \"{x['text'][:160]}\"")


def cmd_brochure(a) -> int:
    return subprocess.call([sys.executable, str(ROOT / "marketing" / "build_brochure.py"), *a.rest], cwd=ROOT)


# ---------------------------------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="wr", description="WorldReach: find businesses abroad and write to them.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="test the settings, the Sheet, every mailbox and our own e-mails")
    pv = sub.add_parser("preview", help="show the e-mails each kind of business would get")
    pv.add_argument("kind", nargs="?", default="", help="only this kind, e.g. gym, salon, hotel")
    pv.add_argument("--all", action="store_true", help="every market, not only the first")
    em = sub.add_parser("emails", help="one outreach run")
    em.add_argument("--dry-run", action="store_true", help="only prepare the e-mails (Email Preview tab)")
    em.add_argument("--max", type=int, default=None, help="this many e-mails now, whatever the time of day")
    em.add_argument("--check", action="store_true", help="only read replies and bounces")
    em.add_argument("--copy-to", default="", help="a blind copy of each first e-mail to this address (yours)")
    em.add_argument("--box", type=int, default=0, help="only this mailbox (its number in the settings)")
    te = sub.add_parser("test", help="spam test: the next first e-mail from every mailbox, only to these addresses")
    te.add_argument("addresses", nargs="+")
    te.add_argument("--box", type=int, default=0)
    le = sub.add_parser("leads", help="find businesses in the next city and their e-mail addresses")
    le.add_argument("--city", default="", help="this city instead, e.g. us/austin")
    le.add_argument("--count", type=int, default=1, help="how many cities this time")
    le.add_argument("--minutes", type=float, default=90.0, help="search time per city")
    le.add_argument("--hunt-minutes", type=float, default=30.0, help="e-mail hunt time per city")
    hu = sub.add_parser("hunt", help="more e-mail hunting in cities searched before")
    hu.add_argument("--minutes", type=float, default=45.0)
    sub.add_parser("status", help="mailboxes, leads, e-mails and replies")
    rp = sub.add_parser("report", help="e-mails per day, bounces, replies")
    rp.add_argument("--days", type=int, default=14)
    rp.add_argument("--limit", type=int, default=30, help="how many replies of each kind to list")
    rp.add_argument("--all", action="store_true", help="also list those who said no")
    sub.add_parser("resume", help="end a sending pause now")
    ol = sub.add_parser("outlook-login", help="sign an Outlook mailbox in, once")
    ol.add_argument("n", type=int, help="the mailbox's number in the settings")
    dn = sub.add_parser("dns", help="check a sending domain's SPF, DKIM and DMARC")
    dn.add_argument("domain")
    wa = sub.add_parser("whatsapp", help="the WhatsApp queue (sends nothing)")
    wa_sub = wa.add_subparsers(dest="action", required=True)
    wa_sub.add_parser("list")
    wn = wa_sub.add_parser("next")
    wn.add_argument("--skip", action="append", default=[])
    wt = wa_sub.add_parser("test")
    wt.add_argument("number")
    wm = wa_sub.add_parser("mark")
    wm.add_argument("row", type=int)
    wm.add_argument("key")
    wm.add_argument("number")
    wm.add_argument("result", choices=["Sent", "Not on WhatsApp", "Replied", "Interested", "Not interested", "Skip"])
    cl = sub.add_parser("client", help="the follow-ups we run for a client: new | list | preview | run | report | stop")
    cl.add_argument("action", choices=["new", "list", "preview", "run", "report", "stop"])
    cl.add_argument("id", nargs="?", default=None, help="the client's folder name, e.g. lotus-yoga")
    cl.add_argument("email", nargs="?", default="", help="for stop: the customer's address")
    cl.add_argument("--all", action="store_true", help="run: every client")
    cl.add_argument("--dry-run", action="store_true", help="run: only count what is due")
    cl.add_argument("--days", type=int, default=30)
    br = sub.add_parser("brochure", help="build the overview PDF again")
    br.add_argument("rest", nargs=argparse.REMAINDER)
    rb = sub.add_parser("robot", help="the robot's timetable: serve | status | log | run JOB")
    rb.add_argument("rest", nargs=argparse.REMAINDER)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    S.data_dir().mkdir(parents=True, exist_ok=True)
    if a.cmd == "robot":
        from . import robot

        return robot.main(a.rest)
    run = {"check": cmd_check, "preview": cmd_preview, "emails": cmd_emails, "test": cmd_test, "leads": cmd_leads,
           "hunt": cmd_hunt, "status": cmd_status, "report": cmd_report, "resume": cmd_resume,
           "outlook-login": cmd_outlook_login, "dns": cmd_dns, "whatsapp": cmd_whatsapp, "brochure": cmd_brochure,
           "client": cmd_client}[a.cmd]
    try:
        if a.cmd in ("emails", "leads", "hunt"):
            try:
                with job_lock(a.cmd):
                    return run(a)
            except Busy as exc:
                print(f"Busy: {exc} is running. Try again when it has finished ( wr status  shows it).")
                return BUSY
        return run(a)
    except C.OutreachConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
