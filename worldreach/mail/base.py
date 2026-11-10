"""What every mailbox does, whatever the provider: send one message, read what came back.

Every outcome of a send is classified, so one bad address never stops a run, while a provider's limit or block stops
that mailbox at once (carrying on would put the account at risk)."""
from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


@dataclass
class SendResult:
    status: str          # sent | invalid | limit | blocked | temp | auth | network
    code: int = 0
    detail: str = ""
    msgid: str = ""      # the Message-ID the provider gave the message, when it replaced ours (Outlook)

    @property
    def ok(self) -> bool:
        return self.status == "sent"


@dataclass
class InboxEvent:
    kind: str            # reply | bounce
    email: str           # our recipient this is about (lower-case)
    reply_kind: str = ""  # positive | negative | other | auto (for replies)
    text: str = ""
    ref: str = ""        # the provider's id of the message (IMAP UID, Graph id), for the report
    at: float = 0.0


@dataclass
class Cursor:
    """Where a mailbox's inbox was read up to (kept in the outreach memory between runs)."""
    data: dict = field(default_factory=dict)


class Mailbox:
    """One sending account. Subclasses: SmtpMailbox (Gmail and others), GraphMailbox (Outlook)."""
    kind = "smtp"
    address = ""

    def check(self) -> str:
        """Sign in without sending. "" if it works, else a reason the owner can act on."""
        raise NotImplementedError

    def send(self, msg: EmailMessage) -> SendResult:
        raise NotImplementedError

    def scan(self, *, known_emails: set[str], known_msgids: dict[str, str], cursor: dict) -> tuple[list[InboxEvent], dict]:
        """Replies and bounces since the cursor. Returns (events, the new cursor)."""
        raise NotImplementedError

    def close(self) -> None:
        pass


def build_message(*, sender_name: str, sender_addr: str, to: str, subject: str, body: str, in_reply_to: str = "",
                  references: list[str] | None = None, attachments: list[tuple[str, bytes]] | None = None,
                  unsubscribe: bool = True) -> EmailMessage:
    """A plain-text e-mail: no HTML, links, images or tracking pixels (what reaches inboxes, not spam folders)."""
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, sender_addr)) if sender_name else sender_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender_addr.rsplit("@", 1)[-1] if "@" in sender_addr else None)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = " ".join(references or [in_reply_to])
    if unsubscribe:
        # Lets mail apps show an "unsubscribe" button; the request arrives as an e-mail and is honoured.
        msg["List-Unsubscribe"] = f"<mailto:{sender_addr}?subject=unsubscribe>"
    msg.set_content(body)
    for name, data in attachments or []:
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    return msg


def body_text(msg: EmailMessage) -> str:
    """The plain-text body, also when the message carries an attachment."""
    part = msg.get_body(preferencelist=("plain",))
    return (part.get_content() if part is not None else "").strip()


def classify_smtp_error(code: int, text: str) -> str:
    """What a mail server's refusal means: invalid (that address), limit (today's quota), blocked (spam policy),
    temp (try later)."""
    t = (text or "").lower()
    if "5.4.5" in t or "sending limit" in t or "quota" in t or "too many" in t or "5.2.252" in t or \
            (code in (421, 451, 452) and ("rate" in t or "limit" in t)):
        return "limit"
    if "5.7." in t and ("spam" in t or "unsolicited" in t or "suspend" in t or "blocked" in t or "policy" in t
                        or "5.7.501" in t or "5.7.708" in t or "5.7.750" in t):
        return "blocked"
    if code in (550, 551, 553) and ("5.1.1" in t or "does not exist" in t or "no such user" in t or "invalid" in t
                                    or "user unknown" in t or "address rejected" in t or "not found" in t
                                    or "5.1.10" in t):
        return "invalid"
    if 500 <= code < 600:
        return "invalid" if "5.1." in t else "blocked"
    return "temp"


def txt(v) -> str:
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v or "")
