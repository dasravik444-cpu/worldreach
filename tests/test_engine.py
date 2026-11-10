"""The sending engine: warm-up, turns between mailboxes, follow-ups, replies, bounces, brakes, country rules."""
from __future__ import annotations

from outreach_helpers import (Clock, FakeMailbox, box, engine, lead_row, make_leads, outreach_config, sheet,
                              status_of, tab)

from worldreach.mail.base import InboxEvent, body_text
from worldreach.outreach import ramp
from worldreach.outreach.store import Store
from worldreach.settings import MailboxConfig


def run_day(store, clock, boxes, mailers, day: str, *, leads=None, client=None, hours=range(8, 21), tz="America/Chicago",
            **kw):
    """One sending day: a run at half past every hour (like the robot)."""
    out = []
    for h in hours:
        clock.set(f"{day} {h:02d}:35", tz)
        eng = engine(store, clock, boxes, mailers, leads=leads, client=client, **kw)
        out.append(eng.run())
    return out


def test_dry_run_prepares_and_checks_the_emails_and_sends_nothing(tmp_path):
    client, session = sheet({"Leads US": [lead_row(i) for i in range(1, 6)]})
    clock = Clock("2026-11-10 10:00")
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    code, summary = engine(store, clock, [box(1)], {"sender1@gmail.com": mb}, client=client, live=False).run()
    assert code == 0 and summary["planned"] == 5 and mb.sent == []
    rows = tab(session, "Email Preview")
    assert len(rows) == 5 and all(r["Text Check"] == "OK" for r in rows), [r["Text Check"] for r in rows]
    assert "Iron Temple 1" in rows[0]["Body"] and "12 Park Street" in rows[0]["Body"]
    assert status_of(session, "Leads US", "AUS-1") == ""
    assert store.box("sender1@gmail.com").get("cap_day") is None      # a look does not start the warm-up


def test_first_day_sends_fifty_spread_over_the_office_hours(tmp_path):
    clock = Clock()
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    leads = make_leads(400)
    run_day(store, clock, [box(1)], {mb.address: mb}, "2026-11-10", leads=leads)
    assert len(mb.sent) == 50
    hours = sorted({int((t - mb.sent[0][0]) // 3600) for t, _ in mb.sent})
    assert len(hours) >= 6                              # not all at once
    gaps = [b[0] - a[0] for a, b in zip(mb.sent, mb.sent[1:])]
    assert min(gaps) >= 45                              # never closer than the smallest gap
    assert len(set(mb.to())) == 50                      # nobody twice


def test_warm_up_follows_the_plan_50_100_200_and_stops_at_the_24_hour_guard(tmp_path):
    clock = Clock()
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    leads = make_leads(6000)
    o = outreach_config(email={"follow_up_days": []})
    per_day = []
    days = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18",
            "2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24"]
    for day in days:
        before = len(mb.sent)
        run_day(store, clock, [box(1)], {mb.address: mb}, day, leads=leads, o=o)
        per_day.append(len(mb.sent) - before)
    assert per_day[:8] == [50, 100, 200, 250, 300, 350, 400, 450]
    assert all(465 <= n <= 480 for n in per_day[8:])    # the top: Gmail's ceiling is for ANY 24 hours, so about 480
    times = [t for t, _ in mb.sent]
    import bisect
    assert max(i + 1 - bisect.bisect_right(times, t - 86400) for i, t in enumerate(times)) <= 480


def test_a_day_the_robot_was_off_is_no_day_of_warm_up_and_there_is_never_a_jump(tmp_path):
    clock = Clock()
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    leads = make_leads(3000)
    o = outreach_config(email={"follow_up_days": []})
    run_day(store, clock, [box(1)], {mb.address: mb}, "2026-11-10", leads=leads, o=o)
    run_day(store, clock, [box(1)], {mb.address: mb}, "2026-11-11", leads=leads, o=o, hours=[9])     # one run only
    sent_day2 = len(mb.sent) - 50
    assert sent_day2 < 50                               # a ninth of the day's 100, far under half
    run_day(store, clock, [box(1)], {mb.address: mb}, "2026-11-12", leads=leads, o=o)
    assert len(mb.sent) - 50 - sent_day2 == 100         # still step 2: yesterday was no full day


def test_two_mailboxes_share_the_leads_and_each_follows_its_own_plan(tmp_path):
    clock = Clock()
    g = FakeMailbox("sender1@gmail.com", clock=clock)
    ol = FakeMailbox("sender2@outlook.com", "outlook", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    leads = make_leads(500)
    run_day(store, clock, [box(1), box(2, "outlook")], {g.address: g, ol.address: ol}, "2026-11-10", leads=leads)
    assert (len(g.sent), len(ol.sent)) == (50, 20)      # Outlook starts lower
    assert not set(g.to()) & set(ol.to())
    assert str(ol.sent[0][1]["From"]).endswith("<sender2@outlook.com>")


def test_follow_ups_come_from_the_same_mailbox_in_the_same_conversation_and_a_reply_stops_them(tmp_path):
    clock = Clock()
    a, b = FakeMailbox("sender1@gmail.com", clock=clock), FakeMailbox("sender2@gmail.com", clock=clock)
    boxes, mailers = [box(1), box(2)], {a.address: a, b.address: b}
    store = Store(str(tmp_path / "o.sqlite"))
    leads = make_leads(6)
    run_day(store, clock, boxes, mailers, "2026-11-10", leads=leads)
    first = {str(m["To"]): (mb.address, m) for mb in (a, b) for _, m in mb.sent}
    assert len(first) == 6
    # one business answers before the follow-up
    replier = "owner1@ausbiz1.com"
    owner_box = a if first[replier][0] == a.address else b
    owner_box.inbox.append(InboxEvent("reply", replier, "other", "Who is this?"))
    run_day(store, clock, boxes, mailers, "2026-11-12", leads=leads)              # two days later: follow-up 1
    for mb in (a, b):
        for _, m in mb.sent:
            if str(m["Subject"]).startswith("Re: ") and str(m["To"]) != "owner@example.org":
                orig_box, orig = first[str(m["To"])]
                assert orig_box == mb.address and m["In-Reply-To"] == orig["Message-ID"]
                assert str(m["Subject"]) == "Re: " + str(orig["Subject"])
    followed = [str(m["To"]) for mb in (a, b) for _, m in mb.sent if "short follow-up" in body_text(m)]
    assert sorted(followed) == sorted(set(first) - {replier})
    run_day(store, clock, boxes, mailers, "2026-11-16", leads=leads)              # day 5 fell on a Sunday: Monday
    last = [str(m["To"]) for mb in (a, b) for _, m in mb.sent if "Last note from me" in body_text(m)]
    assert sorted(last) == sorted(set(first) - {replier})
    run_day(store, clock, boxes, mailers, "2026-11-23", leads=leads)
    assert sum(len(mb.sent) for mb in (a, b)) == 6 + 5 + 5 + 1      # ... + the alert to the owner about the reply
    assert [ld.status for ld in leads if ld.lead_id == "AUS-1"] == ["Replied - read it"]
    assert {ld.status for ld in leads if ld.lead_id != "AUS-1"} == {"Emailed - no reply"}


def test_a_plain_yes_gets_the_overview_at_once_and_the_owner_is_told(tmp_path, monkeypatch):
    pdf = tmp_path / "brochure.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    o = outreach_config(auto_reply={"enabled": True, "attachment": str(pdf)})
    client, session = sheet({"Leads US": [lead_row(1, person="Dana Cole (owner)", phone="+1 512-555-0101"), lead_row(2)]})
    clock = Clock()
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    engine(store, clock, [box(1)], {mb.address: mb}, client=client, o=o, max_emails=2).run()
    assert status_of(session, "Leads US", "AUS-1") == "Emailed"
    mb.inbox += [InboxEvent("reply", "owner1@business1.com", "positive", "Yes please, send it over."),
                 InboxEvent("reply", "owner2@business2.com", "positive", "Not sure what this is. Do you have prices?")]
    clock.sleep(3600)
    code, summary = engine(store, clock, [box(1)], {mb.address: mb}, client=client, o=o, max_emails=0).run()
    assert summary["positive"] == 2 and summary["overviews"] == 1
    overview = [m for _, m in mb.sent if "overview is attached" in body_text(m)]
    assert [str(m["To"]) for m in overview] == ["owner1@business1.com"]
    assert [p.get_filename() for p in overview[0].iter_attachments()] == ["Aurenflow-overview.pdf"]
    assert body_text(overview[0]).startswith("Hi Dana,")
    alert = [m for _, m in mb.sent if str(m["To"]) == "owner@example.org"]
    assert len(alert) == 1 and "2 new replies" in str(alert[0]["Subject"])
    assert "overview PDF went back to them automatically" in body_text(alert[0])
    assert status_of(session, "Leads US", "AUS-1") == "Interested - call now"
    replies = tab(session, "Replies")
    assert {r["Reply Type"] for r in replies} == {"Interested"} and len(replies) == 2


def test_a_no_removes_the_business_for_good(tmp_path):
    client, session = sheet({"Leads US": [lead_row(1, phone="+1 512-555-0101")]})
    clock = Clock()
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    engine(store, clock, [box(1)], {mb.address: mb}, client=client, max_emails=1).run()
    mb.inbox.append(InboxEvent("reply", "owner1@business1.com", "negative", "No thanks, remove us."))
    clock.sleep(3600)
    engine(store, clock, [box(1)], {mb.address: mb}, client=client, max_emails=0).run()
    assert status_of(session, "Leads US", "AUS-1") == "Not interested (opted out)"
    dnc = {r["Email or Phone"] for r in tab(session, "Do Not Contact")}
    assert {"owner1@business1.com", "+15125550101"} <= dnc
    clock.sleep(3 * 86400)
    before = len(mb.sent)
    engine(store, clock, [box(1)], {mb.address: mb}, client=client).run()
    assert len(mb.sent) == before                       # no follow-up, nothing


def test_bad_addresses_are_never_sent_and_too_many_bounces_pause_the_mailbox(tmp_path):
    clock = Clock()
    leads = make_leads(120)
    leads[0].emails = ["noreply@ausbiz1.com"]           # nobody reads it
    leads[1].emails = ["owner@deadsite.com"]            # its domain has no mail server
    rejected = {ld.emails[0] for ld in leads[10:60:5]}  # ten addresses the server refuses
    mb = FakeMailbox("sender1@gmail.com", clock=clock, invalid=rejected)
    store = Store(str(tmp_path / "o.sqlite"))
    out = run_day(store, clock, [box(1)], {mb.address: mb}, "2026-11-10", leads=leads, dead_domains=["deadsite.com"])
    assert not {"noreply@ausbiz1.com", "owner@deadsite.com"} & set(mb.to())
    assert leads[0].status == leads[1].status == "No usable e-mail"
    assert {r["email"] for r in store.q("SELECT email FROM skipped")} == {"noreply@ausbiz1.com", "owner@deadsite.com"}
    st = store.box(mb.address)
    assert st["paused_until"] > clock.now() and "bounced" in st["pause_reason"]
    assert any("SENDING PAUSED" in n for _, s in out for n in s["notes"])
    assert all(ld.status == "Email bounced" for ld in leads if ld.emails[0] in rejected and ld.status != "")
    sent_then = len(mb.sent)
    clock.set("2026-11-10 20:00")
    engine(store, clock, [box(1)], {mb.address: mb}, leads=leads).run()
    assert len([m for _, m in mb.sent if str(m["To"]) != "owner@example.org"]) == \
        len([m for _, m in mb.sent[:sent_then] if str(m["To"]) != "owner@example.org"])   # paused: nothing more


def test_the_providers_limit_pauses_that_mailbox_only_and_it_restarts_lower(tmp_path):
    clock = Clock()
    a = FakeMailbox("sender1@gmail.com", clock=clock, limit_at=30)
    b = FakeMailbox("sender2@gmail.com", clock=clock)
    boxes, mailers = [box(1), box(2)], {a.address: a, b.address: b}
    store = Store(str(tmp_path / "o.sqlite"))
    leads = make_leads(900)
    o = outreach_config(email={"follow_up_days": []})
    run_day(store, clock, boxes, mailers, "2026-11-10", leads=leads, o=o)
    assert len(a.sent) == 30 and len([m for _, m in b.sent if str(m["To"]) != "owner@example.org"]) == 50
    st = store.box(a.address)
    assert "sending limit" in st["pause_reason"] and st["ceiling"] == 50          # never under the first step
    alerts = [m for _, m in b.sent if str(m["To"]) == "owner@example.org"]
    assert alerts and "SENDING PAUSED" in body_text(alerts[0])                    # told through the other mailbox
    a.limit_at = 0
    run_day(store, clock, boxes, mailers, "2026-11-11", leads=leads, o=o)
    assert len(a.sent) - 30 == 50                       # back at the first step, not at 100
    d = ramp.describe(store, o, box(1), "2026-11-11", clock.now())
    assert d["ceiling"] == 50 and not d["paused_until"]


def test_a_spam_block_stops_the_mailbox_for_two_days(tmp_path):
    clock = Clock()
    mb = FakeMailbox("sender1@gmail.com", clock=clock, block_at=12)
    store = Store(str(tmp_path / "o.sqlite"))
    leads = make_leads(300)
    run_day(store, clock, [box(1)], {mb.address: mb}, "2026-11-10", leads=leads)
    assert len(mb.sent) == 11
    run_day(store, clock, [box(1)], {mb.address: mb}, "2026-11-11", leads=leads)
    assert len(mb.sent) == 11                           # still paused
    run_day(store, clock, [box(1)], {mb.address: mb}, "2026-11-13", leads=leads)
    assert 11 < len(mb.sent) <= 11 + 50


def test_uk_only_limited_companies_are_emailed_and_the_email_says_where_the_address_came_from(tmp_path):
    client, session = sheet({"Leads UK": [lead_row(1, prefix="MAN", name="Northern Barbell Ltd", legal="Ltd/LLP/PLC"),
                                          lead_row(2, prefix="MAN", name="Dave's Gym")]})
    clock = Clock("2026-11-10 10:00", "Europe/London")
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    code, summary = engine(store, clock, [box(1)], {mb.address: mb}, client=client, codes=("gb",)).run()
    assert mb.to() == ["owner1@business1.com"] and summary["not_emailed_by_rule"] == 1
    text = body_text(mb.sent[0][1])
    assert 'I found this address on your website or public listing; reply "delete" and I erase it.' in text
    assert "Manchester" in text and status_of(session, "Leads UK", "MAN-2") == ""
    assert any("country's rules ask for consent" in n for n in summary["notes"])


def test_emails_go_out_in_each_business_own_office_hours(tmp_path):
    clock = Clock("2026-11-10 08:00", "America/Chicago")           # 9:00 in New York, 6:00 in Los Angeles
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    leads = (make_leads(3, prefix="AUS", tz="America/Chicago") + make_leads(3, prefix="NYC", tz="America/New_York")
             + make_leads(3, prefix="LAX", tz="America/Los_Angeles"))
    engine(store, clock, [box(1)], {mb.address: mb}, leads=leads).run()
    assert {a.split("@")[1][:3] for a in mb.to()} == {"nyc"}
    clock.set("2026-11-10 18:00", "America/Chicago")               # 16:00 in Los Angeles; Austin and New York closed
    engine(store, clock, [box(1)], {mb.address: mb}, leads=leads).run()
    assert {a.split("@")[1][:3] for a in mb.to()} == {"nyc", "lax"}
    clock.set("2026-11-14 11:00", "America/Chicago")               # a Saturday
    before = len(mb.sent)
    engine(store, clock, [box(1)], {mb.address: mb}, leads=leads).run()
    assert len(mb.sent) == before


def test_the_owner_s_own_status_and_the_do_not_contact_tab_are_respected_and_one_business_gets_one_email(tmp_path):
    rows = [lead_row(1, status="Customer"), lead_row(2), lead_row(3, name="Iron Temple 2 Austin", email="info@business2.com",
                                                                 website="https://www.business2.com/contact"),
            lead_row(4, signals="Objects to advertising"), lead_row(5, email="hello@blocked.com")]
    client, session = sheet({"Leads US": rows})
    session.tabs["Do Not Contact"] = {"id": 77, "rows": [["Email or Phone", "Reason", "Added", "Source"],
                                                         ["@blocked.com", "asked by phone"]]}
    clock = Clock()
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    engine(store, clock, [box(1)], {mb.address: mb}, client=client).run()
    assert mb.to() == ["owner2@business2.com"]


def test_the_spam_test_goes_only_to_the_test_addresses_and_leaves_no_trace(tmp_path):
    client, session = sheet({"Leads US": [lead_row(1), lead_row(2)]})
    clock = Clock("2026-11-14 23:00")                               # any time of day
    a, b = FakeMailbox("sender1@gmail.com", clock=clock), FakeMailbox("sender2@outlook.com", "outlook", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    code, summary = engine(store, clock, [box(1), box(2, "outlook")], {a.address: a, b.address: b}, client=client,
                           test_to=["me@gmail.com", "me@outlook.com"]).run()
    assert code == 0 and sorted(a.to()) == sorted(b.to()) == ["me@gmail.com", "me@outlook.com"]
    assert "Iron Temple" in body_text(a.sent[0][1])
    assert store.q("SELECT * FROM threads") == [] and store.q("SELECT * FROM sends") == []
    assert status_of(session, "Leads US", "AUS-1") == ""


def test_a_mailbox_whose_login_fails_is_left_out_and_the_others_carry_on(tmp_path):
    clock = Clock()
    a = FakeMailbox("sender1@gmail.com", clock=clock, login_problem="sender1@gmail.com: the login was refused")
    b = FakeMailbox("sender2@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    code, summary = engine(store, clock, [box(1), box(2), MailboxConfig(3, "gmail", "")], {a.address: a, b.address: b},
                           leads=make_leads(40)).run()
    assert code == 2 and a.sent == [] and len([t for t in b.to() if t != "owner@example.org"]) > 0
    assert any("mailbox 3" in n and "ADDRESS is missing" in n for n in summary["notes"])
    assert any("login was refused" in body_text(m) for _, m in b.sent if str(m["To"]) == "owner@example.org")


def test_live_needs_the_postal_address_for_the_us(tmp_path):
    clock = Clock()
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    o = outreach_config(sender={"postal_address": ""})
    code, summary = engine(Store(str(tmp_path / "o.sqlite")), clock, [box(1)], {mb.address: mb}, leads=make_leads(3), o=o).run()
    assert code == 1 and "POSTAL_ADDRESS" in summary["notes"][0] and mb.sent == []


def test_whatsapp_queue_takes_published_numbers_of_businesses_email_cannot_reach(tmp_path):
    rows = [lead_row(1, email=" ", whatsapp="+1 512-555-0111"), lead_row(2, whatsapp="+1 512-555-0122"),
            lead_row(3, email=" ", phone="+1 512-555-0133")]
    client, session = sheet({"Leads US": rows})
    clock = Clock()
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "o.sqlite"))
    engine(store, clock, [box(1)], {mb.address: mb}, client=client).run()
    queue = tab(session, "WhatsApp Queue")
    assert [r["Lead ID"] for r in queue] == ["AUS-1"]              # 2 gets the e-mail; 3 publishes no WhatsApp number
    assert queue[0]["Open Chat"].startswith("https://wa.me/15125550111?text=") and "STOP" in queue[0]["Message"]
    # the owner sent it and they said no
    wa = session.tabs["WhatsApp Queue"]["rows"]
    wa[1][wa[0].index("Result")] = "Not interested"
    clock.sleep(3600)
    engine(store, clock, [box(1)], {mb.address: mb}, client=client).run()
    assert status_of(session, "Leads US", "AUS-1") == "Not interested (opted out)"
    assert len(tab(session, "WhatsApp Queue")) == 1
