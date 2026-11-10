"""A trial without sending anything: weeks of the real sending engine against pretend mailboxes and businesses.

    python scripts/simulate.py                    # 3 mailboxes (2 Gmail, 1 Outlook), 4 weeks, normal data
    python scripts/simulate.py --bounce 0.09      # bad addresses: watch the bounce brake
    python scripts/simulate.py --limit-at 260     # a Gmail account that is stopped at 260 a day
    python scripts/simulate.py --weeks 6 --leads 60000

It shows per day what each mailbox sent (first e-mails and follow-ups), the pauses, and at the end how many
businesses were reached. The replies are made up at fixed rates only to exercise the reply handling: they say
nothing about how many real businesses will answer.
"""
from __future__ import annotations

import argparse
import random
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from outreach_helpers import Clock, FakeMailbox, box, engine, make_leads, outreach_config  # noqa: E402

from worldreach.mail.base import InboxEvent  # noqa: E402
from worldreach.outreach.store import Store  # noqa: E402

ZONES = [("NYC", "America/New_York"), ("AUS", "America/Chicago"), ("DEN", "America/Denver"), ("LAX", "America/Los_Angeles")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--leads", type=int, default=40000)
    ap.add_argument("--bounce", type=float, default=0.02, help="share of addresses the mail server rejects")
    ap.add_argument("--reply", type=float, default=0.03, help="share of businesses that answer (made up)")
    ap.add_argument("--limit-at", type=int, default=0, help="mailbox 1 is stopped by its provider at this many in 24 h")
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)
    clock = Clock("2026-11-16 03:00", "America/New_York")
    leads = []
    for prefix, tz in ZONES:
        leads += make_leads(a.leads // len(ZONES), prefix=prefix, tz=tz, city=prefix)
    rng.shuffle(leads)
    invalid = {ld.emails[0] for ld in leads if rng.random() < a.bounce}
    boxes = [box(1), box(2), box(3, "outlook")]
    mailers = {b.key: FakeMailbox(b.address, b.kind, clock=clock, invalid=invalid) for b in boxes}
    mailers[boxes[0].key].limit_at = a.limit_at
    o = outreach_config(auto_reply={"enabled": False})
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(str(Path(tmp) / "o.sqlite"))
        day = date(2026, 11, 16)
        print(f"{'day':<11}" + "".join(f"{b.address:>22}" for b in boxes) + f"{'first':>8}{'follow':>8}{'bounced':>9}  notes")
        answered = set()
        for _ in range(a.weeks * 7):
            before = {k: len([m for _, m in mb.sent if "example.org" not in str(m["To"])]) for k, mb in mailers.items()}
            new = fu = bad = 0
            notes = set()
            for hour in range(8, 21):                   # 08:35 New York ... 20:35 (17:35 in Los Angeles)
                clock.set(f"{day.isoformat()} {hour:02d}:35", "America/New_York")
                # yesterday's businesses answer (made-up rates), to the mailbox that wrote to them
                for t in store.q("SELECT email, mailbox FROM threads WHERE stage='active' AND last_sent<?", (clock.now() - 3600,)):
                    if t["email"] not in answered and rng.random() < a.reply / 10:
                        answered.add(t["email"])
                        kind = rng.choice(["positive", "other", "negative"])
                        mailers[t["mailbox"]].inbox.append(InboxEvent("reply", t["email"], kind, {"positive": "Yes, send it", "other": "Who is this?", "negative": "No thanks"}[kind]))
                code, s = engine(store, clock, boxes, mailers, leads=leads, o=o).run()
                new, fu, bad = new + s["new"], fu + s["followups"], bad + s["bounces"]
                notes |= {n.split(" - ")[0][:70] for n in s["notes"] if "PAUSED" in n}
            sent = [len([m for _, m in mb.sent if "example.org" not in str(m["To"])]) - before[k] for k, mb in mailers.items()]
            if day.weekday() < 5:
                print(f"{day.isoformat():<11}" + "".join(f"{n:>22}" for n in sent) + f"{new:>8}{fu:>8}{bad:>9}  " + "; ".join(sorted(notes)))
            day += timedelta(days=1)
        t = {r["stage"]: r["n"] for r in store.q("SELECT stage, COUNT(*) AS n FROM threads GROUP BY stage")}
        r = {x["kind"]: x["n"] for x in store.q("SELECT kind, COUNT(*) AS n FROM replies GROUP BY kind")}
        total = sum(t.values())
        sends = store.scalar("SELECT COUNT(*) FROM sends WHERE status IN ('sent','invalid')", (), 0)
        print(f"\n{a.weeks} weeks: {total} businesses written to with {sends} e-mails; bounced {t.get('bounced', 0)} "
              f"({100 * t.get('bounced', 0) / max(1, total):.1f}%); replies (made up): {r}")
        twice = store.scalar("SELECT COUNT(*) FROM (SELECT lead_key FROM threads GROUP BY lead_key HAVING COUNT(*)>1)", (), 0)
        print(f"businesses written to by two mailboxes: {twice} (must be 0)")
        return 1 if twice else 0


if __name__ == "__main__":
    sys.exit(main())
