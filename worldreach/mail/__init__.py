"""Mailboxes: one interface for Gmail and other SMTP/IMAP accounts (smtp.py) and Outlook (outlook.py)."""
from __future__ import annotations

from .base import Mailbox, SendResult, body_text, build_message  # noqa: F401


def open_mailbox(cfg, **kw) -> Mailbox:
    """The mailbox for one MAILBOX_n of settings.txt (worldreach/settings.py MailboxConfig)."""
    if cfg.kind == "outlook":
        from .outlook import GraphMailbox

        return GraphMailbox(cfg.address, cfg.client_id, tenant=cfg.tenant, index=cfg.index, **kw)
    from .smtp import SmtpMailbox

    return SmtpMailbox(cfg.address, cfg.password, smtp_host=cfg.smtp_host, smtp_port=cfg.smtp_port,
                       imap_host=cfg.imap_host, kind=cfg.kind, **kw)
