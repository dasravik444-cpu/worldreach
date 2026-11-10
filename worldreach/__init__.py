"""WorldReach: finds local businesses abroad (US, UK, Ireland, ...) and writes to them from several mailboxes.

    leadgen/              the lead finder (open map data + the businesses' own websites)
    worldreach/mail/      the mailboxes: Gmail and other SMTP/IMAP accounts, Outlook (Microsoft Graph)
    worldreach/outreach/  the sending engine: warm-up, follow-ups, replies, bounces, the WhatsApp queue
    worldreach/clients/   the service we sell: follow-up campaigns to a client's own customers
"""
__version__ = "0.1.0"
