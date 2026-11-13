"""The robot's timetable, the commands' helpers, and the files a fresh tablet starts from."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from outreach_helpers import Clock, FakeMailbox, box, engine, make_leads

from worldreach import cli, robot
from worldreach import settings as S
from worldreach.outreach import config as C
from worldreach.outreach.store import Store

ROOT = Path(__file__).resolve().parent.parent
IST = ZoneInfo("Asia/Kolkata")


def ts(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=IST).timestamp()


def test_jobs_come_due_once_and_a_missed_one_is_caught_up_within_its_time():
    leads, emails = robot.JOBS["leads"], robot.JOBS["emails"]
    assert robot.due_slot(leads, {}, ts("2026-11-11 07:59"), None) is None
    slot = robot.due_slot(leads, {}, ts("2026-11-11 08:01"), None)
    assert slot == ts("2026-11-11 08:00")
    assert robot.due_slot(leads, {}, ts("2026-11-11 09:00"), slot) is None           # done for today
    assert robot.due_slot(leads, {}, ts("2026-11-11 13:30"), None) == slot            # tablet was off: still today's
    assert robot.due_slot(leads, {}, ts("2026-11-11 15:00"), None) is None            # too late: tomorrow
    assert robot.due_slot(emails, {}, ts("2026-11-11 10:40"), ts("2026-11-11 09:35")) == ts("2026-11-11 10:35")
    assert robot.due_slot(emails, {}, ts("2026-11-11 10:25"), ts("2026-11-11 09:35")) is None
    assert robot.next_slot(emails, {}, ts("2026-11-11 23:50")) == ts("2026-11-12 00:35")
    assert robot.due_slot(leads, {"ROBOT_LEADS_TIME": "21:15"}, ts("2026-11-11 21:16"), None) == ts("2026-11-11 21:15")


def test_emails_come_before_the_other_jobs_and_a_switched_off_job_never_runs():
    now = ts("2026-11-11 08:36")
    assert robot.pick_due(now, {}, {})[0].name == "emails"
    done = {"jobs": {"emails": {"slot": ts("2026-11-11 08:35")}}}
    assert robot.pick_due(now, done, {})[0].name == "clients"
    done["jobs"]["clients"] = {"slot": ts("2026-11-11 08:20")}
    assert robot.pick_due(now, done, {})[0].name == "update"
    assert robot.pick_due(now, done, {"ROBOT_AUTO_UPDATE": "no", "ROBOT_BACKUP": "no", "ROBOT_LEADS": "no"}) is None


def test_no_email_run_is_started_while_every_market_sleeps(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "load", lambda *a, **k: {"MARKETS": "us,gb"})
    assert robot.office_hours_somewhere(ts("2026-11-11 21:00"))          # 15:30 in London, 10:30 in New York
    assert not robot.office_hours_somewhere(ts("2026-11-11 09:00"))      # night in the US, 3:30 in London
    assert not robot.office_hours_somewhere(ts("2026-11-14 21:00"))      # a Saturday


def test_cities_are_searched_market_by_market_and_one_under_way_is_finished_first(tmp_path, monkeypatch):
    monkeypatch.setenv("WR_DATA_DIR", str(tmp_path))
    order = cli.city_order(["us", "gb", "ie"])
    assert order[:4] == [("us", "austin"), ("gb", "manchester"), ("ie", "dublin"), ("us", "nashville")]
    assert len(order) == 28 + 14 + 4
    assert cli.next_cities(["us", "gb"], 2) == [("us", "austin"), ("gb", "manchester")]
    (tmp_path / "us-austin.sqlite").write_bytes(b"")                   # searched before (and nothing open)
    assert cli.next_cities(["us", "gb"], 1) == [("gb", "manchester")]


def test_status_and_report_read_the_memory(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(S, "load", lambda *a, **k: {"MAILBOX_1": "gmail", "MAILBOX_1_ADDRESS": "sender1@gmail.com",
                                                    "MAILBOX_1_PASSWORD": "x", "MARKETS": "us", "LIVE": "yes"})
    clock = Clock()
    mb = FakeMailbox("sender1@gmail.com", clock=clock)
    store = Store(str(tmp_path / "outreach.sqlite"))
    engine(store, clock, [box(1)], {mb.address: mb}, leads=make_leads(30), max_emails=5).run()
    from worldreach.mail.base import InboxEvent

    mb.inbox.append(InboxEvent("reply", mb.to()[0], "positive", "Yes, send it"))
    clock.sleep(600)
    engine(store, clock, [box(1)], {mb.address: mb}, leads=make_leads(30), max_emails=0).run()
    store.close()
    text = cli.status_text(clock.now())
    assert "LIVE" in text and "sender1@gmail.com (gmail): warm-up day-step 1 of 9, today 6 of 50" in text      # 5 first e-mails + the overview that went back
    assert "5 businesses written to" in text and "interested 1" in text
    data = cli.report_data(Store(str(tmp_path / "outreach.sqlite")), 14, "America/New_York", clock.now())
    assert data["total"]["first"] == 5 and data["total"]["positive"] == 1 and len(data["replies"]) == 1
    assert cli.cmd_report(cli.build_parser().parse_args(["report"])) == 0
    out = capsys.readouterr().out
    assert "Interested - answer these first (1)" in out and "20.0% interested" in out


def test_the_shipped_files_are_consistent():
    for sh in sorted((ROOT / "android").glob("*.sh")) + sorted((ROOT / "server").glob("*.sh")) + [ROOT / "scripts" / "run.sh"]:
        assert subprocess.run(["bash", "-n", str(sh)]).returncode == 0, sh
    o = C.load(ROOT / "config" / "outreach.toml")
    assert o["ramp"]["gmail"][:3] == [50, 100, 200] and o["ramp"]["gmail"][-1] == 500 and o["mode"] == "dry-run"
    example = S.read_file(ROOT / "settings-example.txt")
    assert example["LIVE"] == "no" and example["MARKETS"] == "us,gb,ie" and "MAILBOX_1_PASSWORD" not in example
    assert S.mailboxes(example) == []                 # slots left empty are simply not there
    filled = {**example, **{f"MAILBOX_{i}_ADDRESS": f"m{i}@x.com" for i in (1, 2, 4, 5)}}
    boxes = S.mailboxes(filled)                       # 3 Gmail + 2 Outlook slots; number 3 left empty
    assert [(b.index, b.kind) for b in boxes] == [(1, "gmail"), (2, "gmail"), (4, "outlook"), (5, "outlook")]
    assert all(b.problem() for b in boxes)            # ... and each still needs its password / sign-in
    for code in ("us", "gb", "ie"):
        m = C.load_market(code)
        assert len(m.cities) == len(C.fleet(code)) and len({p for p in m.cities}) == len(m.cities)   # prefixes unique
    prefixes = [p for code in ("us", "gb", "ie") for p in C.load_market(code).cities]
    assert len(prefixes) == len(set(prefixes))
    # nothing personal in the repository: no phone number, no address, no password
    text = (ROOT / "settings-example.txt").read_text() + (ROOT / "marketing" / "brochure.json").read_text()
    assert not re.search(r"\+91[\s\d]{8,}|@gmail\.com", text)
    assert (ROOT / "marketing" / "brochure.pdf").read_bytes().startswith(b"%PDF")
    assert b"edition INT-" in (ROOT / "marketing" / "brochure.pdf").read_bytes()


def test_wr_pdf_takes_the_owner_s_own_copy_from_download(tmp_path, monkeypatch):
    from worldreach.outreach.engine import overview_pdf

    down = tmp_path / "Download"
    down.mkdir()
    monkeypatch.setenv("WR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOWNLOAD_DIR", str(down))
    (tmp_path / "data").mkdir()
    o = C.load(ROOT / "config" / "outreach.toml")
    assert overview_pdf(o) == ROOT / "marketing" / "brochure.pdf"          # the one that comes with the code
    assert cli.cmd_pdf(None) == 1
    (down / "Aurenflow-overview.pdf").write_bytes(b"%PDF-1.4 mine")
    assert cli.cmd_pdf(None) == 0
    assert overview_pdf(o).read_bytes() == b"%PDF-1.4 mine"
