"""The follow-ups we run for a client: who is due, the rules, stops, returns, the report."""
from __future__ import annotations

from datetime import date, timedelta

from outreach_helpers import Clock, FakeMailbox

from worldreach.clients.campaigns import CLIENT_TOML, Client, parse_date
from worldreach.mail.base import InboxEvent, body_text

TODAY = date(2026, 11, 10)


def make_client(tmp_path, rows: list[str], **settings) -> Client:
    folder = tmp_path / "lotus-yoga"
    folder.mkdir(exist_ok=True)
    toml = CLIENT_TOML.replace('sender_name = ""', 'sender_name = "Maria at Lotus Yoga"').replace('\nname = ""', '\nname = "Lotus Yoga"')
    toml = toml.replace('address = ""', 'address = "500 Congress Ave, Austin, TX 78701"')
    toml = toml.replace('review_link = ""', 'review_link = "https://g.page/r/abc/review"')
    toml = toml.replace('visit = "visit"', 'visit = "class"').replace("payment = false", "payment = true")
    for k, v in settings.items():
        old = next(line for line in toml.splitlines() if line.startswith(f"{k} = "))
        toml = toml.replace(old, f"{k} = {v}")
    (folder / "client.toml").write_text(toml)
    (folder / "customers.csv").write_text("Name,Email,Last Visit,Consent,Unpaid\n" + "\n".join(rows) + "\n")
    return Client(folder)


def days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def test_each_customer_gets_the_follow_up_that_fits_and_only_with_consent(tmp_path):
    c = make_client(tmp_path, [
        f"Maria Lopez,maria@x.com,{days_ago(3)},yes,",           # came this week: thank-you + review link
        f"James Reed,james@x.com,{days_ago(50)},yes,",           # due again: one come-back reminder
        f"Priya Shah,priya@x.com,{days_ago(200)},yes,",          # gone for months: win-back
        f"No Consent,nc@x.com,{days_ago(200)},no,",              # never agreed: nothing
        f"Alex Kim,alex@x.com,{days_ago(10)},no,$49",            # a missed payment: reminder (about their account)
        f"Recent,recent@x.com,{days_ago(20)},yes,",              # nothing due
        "broken,not-an-address,2026-01-01,yes,",
    ])
    clock = Clock("2026-11-10 11:00")
    due = {d.customer.email: d for d in c.due_today(clock.now())}
    assert {e: d.campaign for e, d in due.items()} == {"maria@x.com": "review", "james@x.com": "comeback",
                                                      "priya@x.com": "winback", "alex@x.com": "payment"}
    review = due["maria@x.com"]
    assert review.body.startswith("Hi Maria,") and "https://g.page/r/abc/review" in review.body
    assert "your class at Lotus Yoga" in review.body and "reply STOP" in review.body and "500 Congress Ave" in review.body
    assert "($49)" in due["alex@x.com"].body and "STOP" not in due["alex@x.com"].body
    assert c.problems() == []


def test_nothing_goes_out_before_the_client_approved_and_then_only_in_its_hours(tmp_path):
    c = make_client(tmp_path, [f"Maria Lopez,maria@x.com,{days_ago(3)},yes,"])
    clock = Clock("2026-11-10 11:00")
    mb = FakeMailbox("studio@gmail.com", clock=clock)
    stats = c.run(mb, live=True, now_fn=clock.now, sleep_fn=clock.sleep)
    assert stats["sent"] == 0 and "not approved" in stats["note"] and mb.sent == []
    c.close()
    c = make_client(tmp_path, [f"Maria Lopez,maria@x.com,{days_ago(3)},yes,"], approved="true",
                    notify_email='"maria@lotusyoga.com"')
    clock.set("2026-11-10 23:00")
    assert "sending hours" in c.run(mb, live=True, now_fn=clock.now, sleep_fn=clock.sleep)["note"] and mb.sent == []
    clock.set("2026-11-10 11:00")
    assert c.run(mb, live=True, now_fn=clock.now, sleep_fn=clock.sleep)["sent"] == 1
    msg = mb.sent[0][1]
    assert str(msg["From"]) == "Maria at Lotus Yoga <studio@gmail.com>" and "maria@lotusyoga.com" in str(msg["Reply-To"])
    clock.sleep(3600)
    assert c.run(mb, live=True, now_fn=clock.now, sleep_fn=clock.sleep)["sent"] == 0       # asked once per visit


def test_win_back_is_a_series_that_a_stop_or_a_return_ends(tmp_path):
    rows = [f"Priya Shah,priya@x.com,{days_ago(200)},yes,", f"Omar Ali,omar@x.com,{days_ago(150)},yes,",
            f"Lena Berg,lena@x.com,{days_ago(120)},yes,"]
    c = make_client(tmp_path, rows, approved="true")
    clock = Clock("2026-11-10 11:00")
    mb = FakeMailbox("studio@gmail.com", clock=clock)
    assert c.run(mb, live=True, now_fn=clock.now, sleep_fn=clock.sleep)["sent"] == 3
    assert all("We miss you" in str(m["Subject"]) for _, m in mb.sent)
    mb.inbox.append(InboxEvent("reply", "omar@x.com", "negative", "STOP"))
    mb.inbox.append(InboxEvent("reply", "priya@x.com", "other", "Oh hi! Can I come Thursday?"))
    clock.set("2026-11-12 11:00")
    assert c.run(mb, live=True, now_fn=clock.now, sleep_fn=clock.sleep)["sent"] == 0       # too early for note 2
    # Lena came back (the client's new export shows a visit after our note)
    (c.folder / "customers.csv").write_text("Name,Email,Last Visit,Consent,Unpaid\n" + rows[0] + "\n" + rows[1] + "\n"
                                            + "Lena Berg,lena@x.com,2026-11-14,yes,\n")
    clock.set("2026-11-17 11:00")
    stats = c.run(mb, live=True, now_fn=clock.now, sleep_fn=clock.sleep)
    second = [m for _, m in mb.sent[3:]]
    assert {str(m["To"]) for m in second} == {"priya@x.com", "lena@x.com"}
    by_to = {str(m["To"]): m for m in second}
    assert "Still here for you" in str(by_to["priya@x.com"]["Subject"])                    # note 2 of the series
    assert "Thank you from Lotus Yoga" in str(by_to["lena@x.com"]["Subject"])              # she is back: a thank-you
    assert "omar@x.com" not in by_to and stats["sent"] == 2
    r = c.report(30, clock.now())
    assert r["messages"] == {"winback": 4, "review": 1} and r["stops"] == 1
    assert [x["email"] for x in r["returns"]] == ["lena@x.com"] and len(r["replies"]) == 2
    assert not c.stop("omar@x.com", "again") and c.stop("priya@x.com", "by hand")
    assert "Hi Priya," in body_text(by_to["priya@x.com"])


def test_a_review_text_that_offers_something_is_refused(tmp_path):
    c = make_client(tmp_path, [f"Maria Lopez,maria@x.com,{days_ago(3)},yes,"])
    (c.folder / "client.toml").write_text((c.folder / "client.toml").read_text() +
                                          '\n[texts.review]\nsubject = "Thanks"\nbody = "Leave us 5 stars and get a discount: {review_link}"\n')
    c2 = Client(c.folder)
    assert any("Google's rules forbid it" in p for p in c2.problems())


def test_dates_as_booking_systems_export_them():
    assert parse_date("2026-11-03") == parse_date("2026-11-03T14:30:00") == parse_date("11/03/2026") == date(2026, 11, 3)
    assert parse_date("3 Nov 2026") == parse_date("Nov 3, 2026") == date(2026, 11, 3)
    assert parse_date("") is None and parse_date("soon") is None
