"""Bring a lead list into the Google Sheet: a CSV written by `export-csv`, or the zip a GitHub run offered for download
(leads-<city>.zip). Today's rules are applied again (big chains, unusable e-mail addresses), businesses already in
the sheet are left exactly as they are, and a Lead ID another business already has gets the next free number."""
from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter

from .enrich.emails import normalize_email
from .quality import is_chain
from .sheets import LEAD_COLUMNS, SheetsSync


def read_lead_files(paths: list[str]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        if path.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".csv"):
                        rows += list(csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8-sig")))
        else:
            with open(path, encoding="utf-8-sig", newline="") as fh:
                rows += list(csv.DictReader(fh))
    return rows


def _plain(value) -> str:
    """Undo the CSV export's guard against spreadsheet formulas ('=..., '+... and so on)."""
    s = "" if value is None else str(value)
    return s[1:] if s[:1] == "'" and s[1:2] in ("=", "@", "-", "+") else s


def import_leads(sync: SheetsSync, cfg, rows: list[dict], *, dry_run: bool = False) -> dict:
    existing = sync.existing_rows()
    chains = cfg["filters"]["exclude_chains"]
    want = set(cfg["sheets"].get("require_any") or [])
    stats: Counter = Counter()
    out, seen = [], set()
    for raw in rows:
        stats["rows read"] += 1
        row = {c: _plain(raw.get(c, "")).strip() for c in LEAD_COLUMNS}
        key = row["Key"]
        if not key or key in seen:
            stats["left out: no key, or listed twice"] += 1
            continue
        seen.add(key)
        if key in existing:
            stats["already in the sheet"] += 1
            continue
        if is_chain(row["Business Name"], chains):
            stats["left out: big chain"] += 1
            continue
        listed = [e for e in row["Emails"].splitlines() if e.strip()]
        emails = list(dict.fromkeys(e for e in (normalize_email(x) for x in listed) if e))
        if len(emails) < len(listed):
            stats["e-mail addresses dropped (not the business's)"] += len(listed) - len(emails)
        row["Emails"] = "\n".join(emails)
        has = {"email": bool(emails), "whatsapp": bool(row["WhatsApp"]), "phone": bool(row["Phones"]),
               "instagram": bool(row["Instagram"])}
        if want and not any(has[k] for k in want):
            stats["left out: no usable e-mail or WhatsApp"] += 1
            continue
        row["Status"] = row["Status"] or "New"
        out.append(row)
    stats["to add"] = len(out)
    if out and not dry_run:
        added, _, renumbered = sync.upsert_leads(out)
        stats["added to the sheet"] = added
        stats["given a new Lead ID (number taken)"] = len(renumbered)
    return dict(stats)
