"""The warm-up of each mailbox and its brakes.

The plan ([ramp] in config/outreach.toml) is the most e-mails a mailbox may send on its 1st, 2nd, 3rd ... sending
day: for a Gmail account 50, 100, 200, then 250 ... 500. A mailbox moves up one step after a day that went well:

  - at least half of that day's limit really went out (a day the robot was off is not a day of warm-up);
  - no brake stopped it that day;
  - few bounces (under [brakes] hold_bounce_rate over the last 7 days).

It never jumps: today's limit is at most about twice what the mailbox really sent on its best recent day.

The brakes (each one e-mails the owner and shows in  wr status ):

  - the provider says "daily limit": sending from that mailbox pauses until tomorrow, the mailbox goes one step
    down, and for a week it stays under what it had sent when the limit hit;
  - the provider blocks a message as spam: two days' pause, half the volume, two weeks under that level;
  - too many bounces: 12 hours' pause, one step down, and a fresh count afterwards.

Everything is kept per mailbox in the outreach memory (Store.box), so a restart changes nothing.
"""
from __future__ import annotations

from .store import Store

WEEK = 7 * 86400


def steps_for(o: dict, box) -> list[int]:
    """The warm-up steps of one mailbox: its provider's plan, cut at the mailbox's own top (MAILBOX_n_MAX_PER_DAY)."""
    steps = list(o["ramp"].get(box.kind) or o["ramp"]["smtp"])
    top = min(int(o["ramp"]["max_24h"].get(box.kind) or 10**9), box.max_per_day or 10**9)
    steps = [min(s, top) for s in steps]
    return [s for i, s in enumerate(steps) if i == 0 or s > steps[i - 1]] or [top]


def bounce_window(store: Store, addr: str, now: float) -> tuple[int, int]:
    """(sent, bounced) over the last 7 days, but only since the last bounce pause ended (a fresh start)."""
    since = max(now - WEEK, float(store.box(addr).get("bounce_from") or 0))
    return store.sent_since(addr, since), store.bounced_since(addr, since)


def today_cap(store: Store, o: dict, box, day: str, now: float) -> int:
    """The limit of this mailbox for `day` (fixed for the day at its first look)."""
    st = store.box(box.key)
    if st.get("cap_day") == day:
        return int(st["cap"])
    steps = steps_for(o, box)
    step = int(st.get("step") or 0)
    last = st.get("cap_day")
    if last and last < day:
        sent = store.sent_on(box.key, last)
        total, bad = bounce_window(store, box.key, now)
        clean = st.get("braked_day") != last and not (total >= 20 and bad / total >= o["brakes"]["hold_bounce_rate"])
        if clean and sent >= o["ramp"]["good_day_share"] * int(st.get("cap") or 0):
            step += 1
    step = max(0, min(step, len(steps) - 1))
    cap = steps[step]
    # never a jump: at most about twice the best day this mailbox really had lately
    best = store.scalar("SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM sends WHERE mailbox=? AND sent_at>=? "
                        "AND status IN ('sent','invalid') GROUP BY day)", (box.key, now - WEEK), 0)
    cap = min(cap, max(steps[0], int(best * float(o["ramp"]["max_growth"]))))
    if st.get("ceiling") and now < float(st.get("ceiling_until") or 0):
        cap = min(cap, max(1, int(st["ceiling"])))
    store.set_box(box.key, step=step, cap_day=day, cap=cap)
    return cap


def allowance(store: Store, o: dict, box, day: str, now: float) -> tuple[int, str]:
    """(how many e-mails are left of this mailbox's limit for today, the reason when it is 0 because of a pause)."""
    st = store.box(box.key)
    if float(st.get("paused_until") or 0) > now:
        return 0, str(st.get("pause_reason") or "paused")
    return max(0, today_cap(store, o, box, day, now) - store.sent_on(box.key, day)), ""


def room_24h(store: Store, o: dict, box, now: float, ahead: float = 0.0) -> int:
    """How many more e-mails keep this mailbox under its provider's ceiling for ANY 24 hours (a rolling count, not a
    calendar day). ahead: seconds of sending this is asked for; what was sent 24 hours before that time will have
    dropped out of the count by then."""
    top = int(o["ramp"]["max_24h"].get(box.kind) or o["ramp"]["max_24h"]["smtp"])
    if box.max_per_day:
        top = min(top, box.max_per_day)
    return max(0, top - store.sent_since(box.key, now + ahead - 86400))


def _pause(store: Store, addr: str, now: float, hours: float, reason: str, day: str, **more) -> float:
    until = now + hours * 3600
    store.set_box(addr, paused_until=until, pause_reason=reason, braked_day=day, **more)
    store.event(addr, "pause", reason, now)
    return until


def _step_under(steps: list[int], level: int) -> int:
    """The highest step whose limit is not above `level`."""
    under = [i for i, s in enumerate(steps) if s <= level]
    return under[-1] if under else 0


def on_limit(store: Store, o: dict, box, day: str, now: float, detail: str) -> float:
    """The provider refused with "daily sending limit". Returns when sending may start again."""
    steps = steps_for(o, box)
    took = store.sent_since(box.key, now - 86400)
    ceiling = max(steps[0], int(took * 0.85))
    step = min(max(0, int(store.box(box.key).get("step") or 0) - 1), _step_under(steps, ceiling))
    return _pause(store, box.key, now, float(o["brakes"]["limit_pause_hours"]),
                  f"the provider's sending limit was reached after {took} e-mails in 24 hours ({detail[:120]})", day,
                  step=step, cap_day="", ceiling=ceiling, ceiling_until=now + WEEK)


def on_blocked(store: Store, o: dict, box, day: str, now: float, detail: str) -> float:
    """The provider refused a message as spam / policy. The strongest warning there is."""
    steps = steps_for(o, box)
    took = store.sent_since(box.key, now - 86400)
    ceiling = max(steps[0], took // 2)
    step = min(int(store.box(box.key).get("step") or 0) // 2, _step_under(steps, ceiling))
    return _pause(store, box.key, now, float(o["brakes"]["blocked_pause_hours"]),
                  f"the provider blocked a message as spam ({detail[:140]})", day,
                  step=step, cap_day="", ceiling=ceiling, ceiling_until=now + 2 * WEEK)


def check_bounces(store: Store, o: dict, box, day: str, now: float) -> float | None:
    """Pause when too many addresses bounce. Returns the end of the pause, or None."""
    b = o["brakes"]
    if float(store.box(box.key).get("paused_until") or 0) > now:
        return None
    sent, bad = bounce_window(store, box.key, now)
    if sent >= b["pause_min_sends"] and bad >= b["pause_min_bounces"] and bad / sent >= b["pause_bounce_rate"]:
        step = max(0, int(store.box(box.key).get("step") or 0) - 1)
        until = now + float(b["bounce_pause_hours"]) * 3600
        return _pause(store, box.key, now, float(b["bounce_pause_hours"]),
                      f"{bad} of the last {sent} e-mails bounced ({100 * bad / sent:.0f}%) - the addresses need a look",
                      day, step=step, cap_day="", bounce_from=until)
    return None


def resume(store: Store, addr: str, now: float) -> str:
    """End a pause now (wr resume). Returns what was ended ("" if the mailbox was not paused)."""
    st = store.box(addr)
    if float(st.get("paused_until") or 0) <= now:
        return ""
    store.set_box(addr, paused_until=0, bounce_from=now, cap_day="")
    store.event(addr, "resume", "pause ended by the owner", now)
    return str(st.get("pause_reason") or "paused")


def describe(store: Store, o: dict, box, day: str, now: float) -> dict:
    """For  wr status : where a mailbox's warm-up stands (reads only; the day's limit is not fixed by looking)."""
    st = store.box(box.key)
    steps = steps_for(o, box)
    sent, bad = bounce_window(store, box.key, now)
    cap = int(st["cap"]) if st.get("cap_day") == day else None
    return {"address": box.address, "kind": box.kind, "step": int(st.get("step") or 0) + 1, "steps": steps,
            "cap_today": cap, "sent_today": store.sent_on(box.key, day),
            "sent_24h": store.sent_since(box.key, now - 86400),
            "paused_until": float(st.get("paused_until") or 0) if float(st.get("paused_until") or 0) > now else 0,
            "pause_reason": st.get("pause_reason") or "", "bounces": (bad, sent),
            "ceiling": int(st["ceiling"]) if st.get("ceiling") and now < float(st.get("ceiling_until") or 0) else 0}
