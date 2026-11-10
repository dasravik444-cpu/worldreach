"""How far a city's campaign has got, read from its memory file (data/<city>.sqlite) without changing it.

Used by the tablet's runner (which city comes next: a campaign under way is finished first) and by  robot status .
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

# Work still open in a campaign: the map searches and the visits to the businesses' websites and profiles.
OPEN_KINDS = ("search", "site", "social", "insta", "api", "li")
GRACE_DAYS = 7          # a campaign still open this long after its last planned day is left (something is stuck)


def city_progress(db: Path, today: date | None = None) -> dict | None:
    """{"day", "days", "searched_pct", "open", "mapped", "unfinished"} for a city searched before; None otherwise."""
    if not Path(db).is_file():
        return None
    today = today or date.today()
    con = None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        one = lambda sql, *a: con.execute(sql, a).fetchone()[0] or 0  # noqa: E731
        searches = one("SELECT COUNT(*) FROM tasks WHERE kind='search'")
        searched = one("SELECT COUNT(*) FROM tasks WHERE kind='search' AND status IN ('done','failed','skipped')")
        marks = ",".join("?" * len(OPEN_KINDS))
        open_n = one(f"SELECT COUNT(*) FROM tasks WHERE kind IN ({marks}) AND status IN ('pending','running')", *OPEN_KINDS)
        days = one("SELECT COUNT(*) FROM parts")
        mapped = one("SELECT COUNT(*) FROM open_places")
        row = con.execute("SELECT value FROM meta WHERE key='start_date'").fetchone()
    except sqlite3.Error:
        return None
    finally:
        if con is not None:
            con.close()
    try:
        day = (today - date.fromisoformat(str(row[0])[:10])).days + 1 if row else 1
    except ValueError:
        day = 1
    unfinished = searches > 0 and open_n > 0 and day <= max(days, 1) + GRACE_DAYS
    return {"day": max(day, 1), "days": days, "searched_pct": round(100 * searched / searches) if searches else 0,
            "open": open_n, "mapped": mapped, "unfinished": unfinished}
