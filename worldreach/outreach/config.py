"""The outreach settings (config/outreach.toml over the defaults below) and the markets (countries) we sell in.

A market is a folder config/<code>/ of city campaigns (the lead finder's files) plus the rules of that country
(leadgen/country.py). Its leads sit in their own tab of the Sheet ("Leads US", "Leads UK" ...); every lead keeps the
time zone of the city it was found in, because e-mails go out in the business's own office hours.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from ..settings import ROOT

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DEFAULTS: dict = {
    "mode": "dry-run",                    # dry-run: prepare and preview only | live: send
    "markets": ["us", "gb", "ie"],        # which config/<code>/ folders are worked (settings.txt MARKETS overrides)
    "sender": {"name": "", "business": "Aurenflow", "phone": "", "postal_address": "", "website": "",
               "notify_email": "", "booking_link": ""},
    "email": {
        "enabled": True,
        # Follow-ups: days after the first e-mail (any reply stops them). They count towards the daily limit.
        "follow_up_days": [2, 5],
        # The business's own office hours, in its own time zone.
        "window_start": "08:30", "window_end": "16:30", "days": ["mon", "tue", "wed", "thu", "fri"],
        "skip_dates": [],                 # ["2026-11-26", "2026-12-25"]: nothing goes out on these dates
        "day_tz": "America/New_York",     # the "day" of the daily limits (its midnight is quiet in the US and Europe)
        "min_gap_seconds": 45, "max_gap_seconds": 240,   # between two e-mails of the same mailbox
        "run_budget_minutes": 50, "max_per_run": 70,
        "one_per_domain": True,           # one conversation per business website
        "send_risky": False,              # also addresses the checker is unsure about (worldreach/mail/verify.py)
        "include_unverified": False,      # also guessed info@/contact@ addresses (they bounce more)
        "attachment": "",                 # a PDF on FIRST e-mails: leave empty (attachments from new accounts go to spam)
        "boost_categories": [],
    },
    # The warm-up: the most e-mails a mailbox may send on its 1st, 2nd, 3rd ... sending day (first e-mails and
    # follow-ups together). A day counts when it went well; a brake holds or lowers it (worldreach/outreach/ramp.py).
    "ramp": {
        "gmail": [50, 100, 200, 250, 300, 350, 400, 450, 500],
        "outlook": [20, 40, 60, 90, 120, 160, 200, 250, 300],
        "smtp": [30, 60, 100, 150, 200, 250, 300, 400, 500],
        # Never more than this from one mailbox in any 24 hours (Gmail stops a free account for a day at 500,
        # Outlook.com at about 300; the gap is kept for your own replies to interested businesses).
        "max_24h": {"gmail": 480, "outlook": 280, "smtp": 480},
        "good_day_share": 0.5,            # a day counts for the warm-up when at least this share of its limit went out
        "max_growth": 2.2,                # never more than this times what the mailbox really sent on its best recent day
    },
    "brakes": {
        "hold_bounce_rate": 0.03,         # from this bounce rate the limit stops rising
        "pause_bounce_rate": 0.06,        # from this one sending pauses and the limit drops a step
        "pause_min_sends": 40, "pause_min_bounces": 4, "bounce_pause_hours": 12,
        "limit_pause_hours": 20, "blocked_pause_hours": 48,
    },
    # A business answers "yes" / "send me details": the overview PDF goes back at once, in the same conversation.
    "auto_reply": {"enabled": True, "attachment": "marketing/brochure.pdf"},
    "whatsapp": {"enabled": True, "start_per_day": 5, "step": 5, "step_every_days": 3, "max_per_day": 25,
                 "max_waiting_days": 5},
    "tabs": {"outreach": "Outreach", "preview": "Email Preview", "replies": "Replies", "whatsapp": "WhatsApp Queue",
             "dnc": "Do Not Contact", "report": "Outreach Report"},
    "texts": {},                          # replace a text: [texts] first = "...", subjects = [...], see templates.py
    "hooks": {},
}


class OutreachConfigError(ValueError):
    pass


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def minutes(hhmm: str) -> int:
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def validate(o: dict) -> None:
    errors = []
    if o["mode"] not in ("dry-run", "live"):
        errors.append('mode must be "dry-run" or "live"')
    e = o["email"]
    f = e["follow_up_days"]
    if not (isinstance(f, list) and len(f) <= 4 and all(isinstance(x, int) and 1 <= x <= 45 for x in f)
            and f == sorted(set(f))):
        errors.append("email.follow_up_days must be increasing whole days, at most 4, e.g. [2, 5]")
    for name in ("window_start", "window_end"):
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", str(e.get(name, ""))):
            errors.append(f"email.{name} must be HH:MM")
    if not errors and minutes(e["window_start"]) >= minutes(e["window_end"]):
        errors.append("email.window_start must be before window_end")
    if not e.get("days") or not set(e["days"]) <= set(DAY_NAMES):
        errors.append('email.days must list days like ["mon", "tue"]')
    try:
        if not 20 <= float(e["min_gap_seconds"]) <= float(e["max_gap_seconds"]) <= 3600:
            errors.append("email gaps must satisfy 20 <= min_gap_seconds <= max_gap_seconds <= 3600")
    except (TypeError, ValueError):
        errors.append("email gaps must be numbers")
    r = o["ramp"]
    for kind in ("gmail", "outlook", "smtp"):
        steps = r.get(kind)
        if not (isinstance(steps, list) and steps and all(isinstance(x, int) and 1 <= x <= 2000 for x in steps)
                and steps == sorted(steps)):
            errors.append(f"ramp.{kind} must be a rising list of whole numbers, e.g. [50, 100, 200]")
        elif steps[-1] > int(r["max_24h"].get(kind, 0) or 0) + 50:
            errors.append(f"ramp.{kind} ends at {steps[-1]}, far above max_24h.{kind}")
    b = o["brakes"]
    if not 0 < float(b["hold_bounce_rate"]) <= float(b["pause_bounce_rate"]) < 1:
        errors.append("brakes: 0 < hold_bounce_rate <= pause_bounce_rate < 1")
    if errors:
        raise OutreachConfigError("config/outreach.toml:\n  - " + "\n  - ".join(errors))


def load(path: str | Path | None = None, settings: dict | None = None) -> dict:
    """config/outreach.toml over the defaults; the sender's details and MARKETS / LIVE come from settings.txt."""
    path = Path(path) if path else ROOT / "config" / "outreach.toml"
    raw = {}
    if path.is_file():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise OutreachConfigError(f"{path} is not valid TOML: {exc}") from exc
    o = _merge(DEFAULTS, raw)
    if settings:
        from .. import settings as S

        mine = {k: v for k, v in S.sender(settings).items() if v}
        o["sender"] = {**o["sender"], **mine}
        if settings.get("MARKETS"):
            o["markets"] = [m.strip().lower() for m in str(settings["MARKETS"]).split(",") if m.strip()]
        if settings.get("LIVE"):
            o["mode"] = "live" if S.flag(settings, "LIVE", False) else "dry-run"
    validate(o)
    return o


# ---------------------------------------------------------------------------------------------------- markets
@dataclass
class Market:
    code: str                              # the folder: "us"
    country: str                           # "US": the country pack (leadgen/country.py)
    name: str
    leads_tab: str
    default_tz: str
    cities: dict = field(default_factory=dict)       # lead-id prefix -> (city name, time zone)
    categories: list = field(default_factory=list)   # [{key, label, ...}] of the market's campaigns
    language: str = "en"

    def tz_of(self, lead_id: str) -> str:
        prefix = re.sub(r"[^A-Za-z]", "", (lead_id or "").split("-")[0]).upper()
        return self.cities.get(prefix, ("", self.default_tz))[1]

    def city_of(self, lead_id: str) -> str:
        prefix = re.sub(r"[^A-Za-z]", "", (lead_id or "").split("-")[0]).upper()
        return self.cities.get(prefix, ("", ""))[0]


def city_files(code: str, root: Path | None = None) -> list[Path]:
    folder = (root or ROOT) / "config" / code
    return sorted(p for p in folder.glob("*.toml") if not p.name.startswith("_") and p.name != "fleet.toml")


def fleet(code: str, root: Path | None = None) -> list[str]:
    """The market's cities in the order they are searched (config/<code>/fleet.toml)."""
    path = (root or ROOT) / "config" / code / "fleet.toml"
    if not path.is_file():
        return [p.stem for p in city_files(code, root)]
    return list(tomllib.loads(path.read_text(encoding="utf-8")).get("cities") or [])


def load_market(code: str, root: Path | None = None) -> Market:
    """Read a market from its city files (each: [campaign] country, timezone, lead_id_prefix; [area] name;
    [sheets] leads_tab)."""
    from leadgen.config import load_config
    from leadgen.country import PACKS

    files = city_files(code, root)
    if not files:
        raise OutreachConfigError(f"market '{code}': no city files in config/{code}/")
    cities: dict = {}
    first = None
    for path in files:
        cfg = load_config(str(path))
        first = first or cfg
        c = cfg["campaign"]
        cities[str(c.get("lead_id_prefix") or "").upper()] = (cfg["area"].get("name") or path.stem, c["timezone"])
    country = first["campaign"]["country"]
    return Market(code=code, country=country, name=PACKS[country].name, leads_tab=first["sheets"]["leads_tab"],
                  default_tz=first["campaign"]["timezone"], cities=cities,
                  categories=[dict(c) for c in first["categories"]], language=PACKS[country].language)


def load_markets(codes: list[str], root: Path | None = None) -> list[Market]:
    return [load_market(c, root) for c in codes]
