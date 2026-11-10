"""A mailbox reached over SMTP (sending) and IMAP (reading), signed in with an app password: Gmail, and any mailbox
on your own domain (Google Workspace, Zoho, Fastmail ...).

Reading is private and read-only: only message headers are read to find what concerns outreach; a body is opened
only when the message comes from a business we e-mailed, refers to one of our messages, or is a bounce about one of
them. Nothing is marked as read, moved or deleted."""
from __future__ import annotations

import email
import imaplib
import re
import smtplib
import socket
import ssl
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr

from ..outreach.classify import bounced_addresses, classify_reply, is_bounce, new_text
from .base import InboxEvent, Mailbox, SendResult, classify_smtp_error, txt

HEADER_FIELDS = "FROM SUBJECT IN-REPLY-TO REFERENCES X-FAILED-RECIPIENTS AUTO-SUBMITTED X-AUTOREPLY PRECEDENCE"
MAX_BODY_BYTES = 3_000_000


def message_text(msg) -> str:
    """The readable text of a received message (bounces are multipart/report: every text part)."""
    part = msg.get_body(preferencelist=("plain", "html")) if hasattr(msg, "get_body") else None
    if part is None:
        texts = []
        for p in msg.walk():
            if p.get_content_maintype() == "text" or p.get_content_type() == "message/delivery-status":
                try:
                    texts.append(p.get_content() if p.get_content_type() != "message/delivery-status" else str(p))
                except Exception:  # noqa: BLE001 - an odd encoding: the raw part will do
                    texts.append(str(p.get_payload()))
        return "\n".join(t if isinstance(t, str) else str(t) for t in texts)
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = strip_html(text)
    return text


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    return re.sub(r"<[^>]+>", " ", text)


class SmtpMailbox(Mailbox):
    def __init__(self, address: str, password: str, *, smtp_host: str = "smtp.gmail.com", smtp_port: int = 587,
                 imap_host: str = "imap.gmail.com", kind: str = "gmail", smtp_factory=smtplib.SMTP,
                 imap_factory=None, timeout: float = 40):
        self.address = address.lower()
        self.password = password.replace(" ", "")      # Google shows the app password in groups of 4
        self.kind = kind
        self.smtp_host, self.smtp_port, self.imap_host = smtp_host, smtp_port, imap_host
        self.smtp_factory = smtp_factory
        self.imap_factory = imap_factory or (lambda: imaplib.IMAP4_SSL(self.imap_host, 993))
        self.timeout = timeout
        self.smtp = None

    # ------------------------------------------------------------------ sending
    def _connect(self) -> None:
        s = self.smtp_factory(self.smtp_host, self.smtp_port, timeout=self.timeout)
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
        try:
            s.login(self.address, self.password)
        except smtplib.SMTPServerDisconnected as exc:
            # Gmail answers a refused password (the normal password instead of an app password) and hangs up;
            # smtplib's next login method then sees the closed connection. It is a login refusal.
            raise smtplib.SMTPAuthenticationError(534, b"the server closed the connection during login (password "
                                                       b"refused; Application-specific password required)") from exc
        self.smtp = s

    def check(self) -> str:
        try:
            self._connect()
            return ""
        except smtplib.SMTPAuthenticationError as exc:
            said = txt(exc.smtp_error).replace("\n", " ")[:160]
            hint = (" - it must be an app password (Gmail: 16 letters from myaccount.google.com/apppasswords, with "
                    "2-Step Verification on), not the account's normal password")
            return f"{self.address}: the login was refused ({exc.smtp_code}: {said}){hint}"
        except (smtplib.SMTPException, OSError, socket.timeout) as exc:
            return f"{self.address}: could not reach {self.smtp_host}:{self.smtp_port} ({type(exc).__name__}: {exc})"
        finally:
            self.close()

    def send(self, msg: EmailMessage) -> SendResult:
        for attempt in (1, 2):
            try:
                if self.smtp is None:
                    self._connect()
                refused = self.smtp.send_message(msg)
                if refused:
                    code, text = next(iter(refused.values()))
                    return SendResult(classify_smtp_error(code, txt(text)), code, txt(text))
                return SendResult("sent")
            except smtplib.SMTPAuthenticationError as exc:
                self.close()
                return SendResult("auth", exc.smtp_code, txt(exc.smtp_error))
            except smtplib.SMTPRecipientsRefused as exc:
                code, text = next(iter(exc.recipients.values()))
                return SendResult(classify_smtp_error(code, txt(text)), code, txt(text))
            except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
                return SendResult(classify_smtp_error(exc.smtp_code, txt(exc.smtp_error)), exc.smtp_code,
                                  txt(exc.smtp_error))
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError, socket.timeout) as exc:
                self.close()
                if attempt == 2:
                    return SendResult("network", 0, f"{type(exc).__name__}: {exc}")
            except smtplib.SMTPResponseException as exc:
                return SendResult(classify_smtp_error(exc.smtp_code, txt(exc.smtp_error)), exc.smtp_code,
                                  txt(exc.smtp_error))
            except smtplib.SMTPException as exc:
                return SendResult("temp", 0, f"{type(exc).__name__}: {exc}")
        return SendResult("network")

    def close(self) -> None:
        if self.smtp is not None:
            try:
                self.smtp.quit()
            except Exception:  # noqa: BLE001 - already gone
                pass
            self.smtp = None

    # ------------------------------------------------------------------ reading
    def scan(self, *, known_emails: set[str], known_msgids: dict[str, str], cursor: dict,
             max_messages: int = 400) -> tuple[list[InboxEvent], dict]:
        last_uid, uidvalidity = cursor.get("uid"), cursor.get("validity")
        m = self.imap_factory()
        try:
            m.login(self.address, self.password)
            typ, _ = m.select("INBOX", readonly=True)
            if typ != "OK":
                raise imaplib.IMAP4.error("cannot open INBOX")
            typ, st = m.status("INBOX", "(UIDNEXT UIDVALIDITY)")
            info = st[0].decode() if st and isinstance(st[0], bytes) else str(st[0] if st else "")
            uidnext = int(re.search(r"UIDNEXT (\d+)", info).group(1))
            validity = re.search(r"UIDVALIDITY (\d+)", info).group(1)
            if last_uid is None or uidvalidity != validity:
                # First look (or the mailbox was rebuilt): start from now, never read old mail.
                return [], {"uid": uidnext - 1, "validity": validity}
            if uidnext - 1 <= last_uid:
                return [], {"uid": last_uid, "validity": validity}
            typ, data = m.uid("SEARCH", None, f"UID {last_uid + 1}:*")
            uids = sorted(int(x) for x in (data[0] or b"").split() if int(x) > last_uid)[:max_messages]
            events: list[InboxEvent] = []
            newest = last_uid
            for i in range(0, len(uids), 50):
                batch = uids[i:i + 50]
                typ, data = m.uid("FETCH", ",".join(map(str, batch)),
                                  f"(UID RFC822.SIZE BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])")
                for item in data or []:
                    if not isinstance(item, tuple):
                        continue
                    meta = item[0].decode("latin-1")
                    uid = int(re.search(r"UID (\d+)", meta).group(1))
                    ms = re.search(r"RFC822\.SIZE (\d+)", meta)
                    newest = max(newest, uid)
                    headers = {k.lower(): str(v) for k, v in email.message_from_bytes(item[1] or b"",
                                                                                      policy=policy.default).items()}
                    events.extend(self._consider(m, uid, int(ms.group(1)) if ms else 0, headers, known_emails,
                                                 known_msgids))
            return events, {"uid": max(newest, uids[-1] if uids else last_uid), "validity": validity}
        finally:
            try:
                m.logout()
            except Exception:  # noqa: BLE001
                pass

    def _consider(self, m, uid: int, size: int, h: dict, known_emails: set[str],
                  known_msgids: dict[str, str]) -> list[InboxEvent]:
        sender = parseaddr(h.get("from", ""))[1].lower()
        subject = h.get("subject", "")
        refs = re.findall(r"<[^>]+>", (h.get("in-reply-to", "") + " " + h.get("references", "")))
        bounce = is_bounce(h.get("from", ""), subject)
        # The conversation this belongs to: by sender, or by our Message-ID in its reply chain (a reply can come
        # from another address of the same business).
        thread_email = sender if sender in known_emails else next((known_msgids[r] for r in refs if r in known_msgids), "")
        if sender == self.address or not (bounce or thread_email) or size > MAX_BODY_BYTES:
            return []
        typ, data = m.uid("FETCH", str(uid), "(BODY.PEEK[])")
        raw = next((x[1] for x in data or [] if isinstance(x, tuple)), b"")
        msg = email.message_from_bytes(raw, policy=policy.default)
        body = message_text(msg)
        if bounce:
            hits = bounced_addresses(h, body, known_emails)
            if not hits and thread_email:
                hits = {thread_email}
            return [InboxEvent("bounce", e, ref=str(uid)) for e in sorted(hits)]
        # every header of the message (helpdesk systems mark theirs), not only the few read to find it
        kind = classify_reply(subject, body, {**{k.lower(): str(v) for k, v in msg.items()}, **h})
        return [InboxEvent("reply", thread_email, kind, new_text(body), str(uid))]
