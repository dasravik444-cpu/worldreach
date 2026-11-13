"""The owner's settings (settings.txt): keys, mailboxes, the sender's details. Never in git.

    WR_SHEET_ID=...                     the Google Sheet
    SENDER_NAME=Ravik                   shown as the sender and under every e-mail
    SENDER_BUSINESS=Aurenflow
    SENDER_PHONE=+91 ...                WhatsApp / phone under every e-mail
    POSTAL_ADDRESS=...                  required by US and Canadian law in every sales e-mail
    NOTIFY_EMAIL=...                    where "a business replied" alerts go

    MAILBOX_1=gmail                     gmail | outlook | smtp
    MAILBOX_1_ADDRESS=you@gmail.com
    MAILBOX_1_PASSWORD=abcd efgh ...    gmail/smtp: the app password (outlook signs in with  wr outlook-login 1 )
    MAILBOX_2=outlook
    MAILBOX_2_ADDRESS=you@outlook.com
    OUTLOOK_CLIENT_ID=...               the "Application (client) ID" of your Microsoft app registration

Up to MAX_MAILBOXES mailboxes. A mailbox of kind smtp also takes MAILBOX_n_SMTP_HOST, _SMTP_PORT, _IMAP_HOST
(a mailbox on your own domain: Google Workspace, Zoho, Fastmail ...).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_MAILBOXES = 6
KINDS = ("gmail", "outlook", "smtp")
# Hosts of the well-known providers; kind "smtp" names its own.
PRESETS = {"gmail": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "imap_host": "imap.gmail.com"}}


def data_dir() -> Path:
    return Path(os.environ.get("WR_DATA_DIR") or ROOT / "data")


def secrets_dir() -> Path:
    return Path(os.environ.get("WR_SECRETS_DIR") or ROOT / "secrets")


@dataclass(frozen=True)
class MailboxConfig:
    index: int                 # 1..MAX_MAILBOXES, the number in settings.txt
    kind: str                  # gmail | outlook | smtp
    address: str
    password: str = ""
    name: str = ""             # sender name for this mailbox (default: SENDER_NAME)
    smtp_host: str = ""
    smtp_port: int = 587
    imap_host: str = ""
    client_id: str = ""        # outlook: the Microsoft app registration
    tenant: str = "common"     # outlook: "consumers" (outlook.com), "organizations" or a tenant id
    max_per_day: int = 0       # 0 = the warm-up plan's own top
    same_as: int = 0           # the number of an earlier mailbox with the same address (a typing mistake)

    @property
    def key(self) -> str:
        return self.address.lower()

    @property
    def domain(self) -> str:
        return self.address.rsplit("@", 1)[-1].lower() if "@" in self.address else ""

    def problem(self) -> str:
        """Why this mailbox cannot be used yet ("" when its settings are complete)."""
        if self.kind not in KINDS:
            return f"MAILBOX_{self.index} must be one of: {', '.join(KINDS)}"
        if "@" not in self.address:
            return f"MAILBOX_{self.index}_ADDRESS is missing"
        if self.same_as:
            return f"the same address as mailbox {self.same_as}: each mailbox needs its own address"
        typo = mistyped_domain(self.domain)
        if typo:
            return f"{self.domain} looks mistyped - did you mean {typo}?"
        if self.kind == "outlook":
            return "" if self.client_id else "OUTLOOK_CLIENT_ID is missing (docs/OUTLOOK.md)"
        if not self.password:
            return f"MAILBOX_{self.index}_PASSWORD is missing (the app password)"
        if self.kind == "smtp" and not (self.smtp_host and self.imap_host):
            return f"MAILBOX_{self.index}_SMTP_HOST and MAILBOX_{self.index}_IMAP_HOST are missing"
        return ""


PROVIDER_DOMAINS = ("gmail.com", "googlemail.com", "outlook.com", "outlook.in", "hotmail.com", "live.com", "msn.com",
                    "yahoo.com", "icloud.com")


def mistyped_domain(domain: str) -> str:
    """The provider domain this one is one or two letters away from ("gmaio.com" -> "gmail.com"); "" if none."""
    import difflib

    if not domain or domain in PROVIDER_DOMAINS:
        return ""
    close = difflib.get_close_matches(domain, PROVIDER_DOMAINS, n=1, cutoff=0.8)
    return close[0] if close else ""


def read_file(path: Path) -> dict:
    """KEY=VALUE lines of a settings file ("#" comments, optional quotes)."""
    out: dict = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            out[key.strip().upper()] = value
    return out


def load(path: Path | None = None, env: dict | None = None) -> dict:
    """settings.txt merged over the environment (the file wins: it is what the owner sees and edits)."""
    env = dict(os.environ if env is None else env)
    file = read_file(path or ROOT / "settings.txt")
    return {**{k: v for k, v in env.items() if k.isupper()}, **file}


def export(settings: dict) -> None:
    """What the lead finder reads from the environment: the Sheet and the Google key file."""
    for key in ("WR_SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_FILE", "BRAVE_API_KEY"):
        if settings.get(key):
            os.environ[key] = settings[key]
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE"):
        key = find_google_key()
        if key:
            os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] = key
    os.environ.setdefault("PYTHONUTF8", "1")


def find_google_key() -> str:
    """The Google service-account key file (.json, any name) in the secrets folder."""
    import json

    for p in sorted(secrets_dir().glob("*.json")):
        try:
            if json.loads(p.read_text(encoding="utf-8-sig")).get("type") == "service_account":
                return str(p)
        except (OSError, ValueError, AttributeError):
            continue
    return ""


def mailboxes(settings: dict) -> list[MailboxConfig]:
    out = []
    for i in range(1, MAX_MAILBOXES + 1):
        kind = str(settings.get(f"MAILBOX_{i}") or "").strip().lower()
        addr = str(settings.get(f"MAILBOX_{i}_ADDRESS") or "").strip()
        if not addr:                    # a slot left empty in settings.txt is simply not there
            continue
        g = lambda name, default="": str(settings.get(f"MAILBOX_{i}_{name}") or default).strip()  # noqa: E731
        preset = PRESETS.get(kind, {})
        try:
            port = int(g("SMTP_PORT") or preset.get("smtp_port", 587))
            top = int(g("MAX_PER_DAY") or 0)
        except ValueError:
            port, top = 587, 0
        out.append(MailboxConfig(
            index=i, kind=kind or "gmail", address=addr, password=g("PASSWORD").replace(" ", ""), name=g("NAME"),
            smtp_host=g("SMTP_HOST") or preset.get("smtp_host", ""), smtp_port=port,
            imap_host=g("IMAP_HOST") or preset.get("imap_host", ""),
            client_id=g("CLIENT_ID") or str(settings.get("OUTLOOK_CLIENT_ID") or "").strip(),
            tenant=g("TENANT") or str(settings.get("OUTLOOK_TENANT") or "common").strip(), max_per_day=top))
    from dataclasses import replace

    first: dict[str, int] = {}
    for i, b in enumerate(out):
        if b.key in first:
            out[i] = replace(b, same_as=first[b.key])
        else:
            first[b.key] = b.index
    return out


def sender(settings: dict) -> dict:
    g = lambda k: str(settings.get(k) or "").strip()  # noqa: E731
    return {"name": g("SENDER_NAME"), "business": g("SENDER_BUSINESS"), "phone": g("SENDER_PHONE"),
            "postal_address": g("POSTAL_ADDRESS"), "website": g("SENDER_WEBSITE"), "notify_email": g("NOTIFY_EMAIL"),
            "booking_link": g("BOOKING_LINK")}


def flag(settings: dict, key: str, default: bool = True) -> bool:
    v = str(settings.get(key) or "").strip().lower()
    return default if not v else v in ("1", "yes", "true", "on")
