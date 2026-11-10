"""Understand incoming mail: is it a reply (interested / not interested / other), an auto-reply or a bounce?"""
from __future__ import annotations

import re

# Strong "stop" wording anywhere in the new text means: never contact again.
NEGATIVE = re.compile(
    r"\b(not\s+interested|no\s+thanks?|no\s+thank\s+you|unsubscribe|remove\s+(me|us|my|our)|stop\s+(e-?mailing|sending|messaging|contacting)"
    r"|do\s*n[o']?t\s+(e-?mail|contact|message|write|send)|not\s+(required|needed|looking)|no\s+requirement|no\s+need"
    r"|spam|take\s+(me|us)\s+off|opt\s*-?\s*out|desinscri\w*|d(?:é|e)sabonn\w*|uitschrijven|afmelden|darse\s+de\s+baja"
    # German
    r"|kein\s+interesse|nicht\s+interessiert|bitte\s+(?:keine|nicht\s+mehr)|abmelden|austragen|l(?:ö|oe)schen|"
    r"keine\s+(?:werbung|e-?mails?|post|anrufe|nachrichten)|unterlassen|abmahn\w*)\b", re.I)
# A reply that is only "no" / "nope" / "nahi" is also an opt-out.
NEGATIVE_SHORT = re.compile(r"^\s*(no|nope|nah|stop|not now|nein|nee|non|delete|remove|unsubscribe|pass)[\s.!]*$", re.I)
POSITIVE = re.compile(
    r"\b(yes|yeah|yep|sure|ok(ay)?|interested|please\s+(send|share|call)|send\s+(it|me|us|the|your)|share\s+(it|the|your)"
    r"|price\s*list|prices?|(?:your|the)\s+rates?|quote|quotation|catalogu?e|brochure|call\s+(me|us)|whats\s*app|details|let'?s\s+talk"
    r"|overview|more\s+info(rmation)?|tell\s+me\s+more|sounds\s+(good|great|interesting)|how\s+much|what\s+does\s+it\s+cost|go\s+ahead"
    r"|preview|demo|ja|gerne?|interessiert|bitte\s+(?:schicken|senden|zusenden|melden)|schicken\s+sie|rufen\s+sie|"
    r"vorschau|angebot|preis\w*|termin)\b", re.I)
AUTO_SUBJECT = re.compile(r"(out\s+of\s+(the\s+)?office|automatic\s+reply|auto-?reply|autoreply|away\s+from|on\s+leave|vacation"
                          r"|abwesenheit|automatische\s+antwort|nicht\s+im\s+b(?:ü|ue)ro|urlaub|eingangsbest(?:ä|ae)tigung"
                          r"|thank\s+you\s+for\s+(your\s+)?(e-?mail|message|contacting)|we\s+have\s+received\s+your)", re.I)
# A machine answering, read in the message itself (8 November 2026: a "rate us" survey counted as interested and a
# hotel's "we acknowledge the receipt of your email" as a reply): receipts, tickets, surveys, do-not-reply notes.
AUTO_TEXT = re.compile(           # strong: only machines write this
    r"(acknowledge\s+(the\s+)?receipt|(this|it)\s+is\s+an?\s+(auto(matic|mated)?|system)[\s-]+(generated\s+)?"
    r"(reply|response|e-?mail|message)|(please\s+)?do\s+not\s+reply|no-?reply|rate\s+us|how\s+(was|would\s+you\s+rate)"
    r"\s+your\s+(experience|interaction)|your\s+opinion\s+matters|(customer|guest)\s+(satisfaction|feedback)\s+survey|csat"
    r"|(ticket|case|complaint|reference)\s*(id|no\.?|number|#)\s*[:#]?\s*\w*\d|your\s+(ticket|case|request|query)\s+"
    r"(has\s+been|is\s+being|was)\s+(created|registered|logged|received|raised)|out\s+of\s+(the\s+)?office"
    r"|on\s+leave\s+(till|until|from))", re.I)
AUTO_WEAK = re.compile(           # weak: a machine's usual words, but a polite person may write them too
    r"(thank\s+you\s+for\s+(writing|contacting|reaching\s+out|getting\s+in\s+touch|your\s+(e-?mail|mail|message|enquiry|"
    r"inquiry|query|request))|we\s+(have\s+)?received\s+your|(shall|will)\s+(get\s+back|revert|respond)\s+(to\s+you\s+)?"
    r"(shortly|soon|at\s+the\s+earliest|within)|(customer|guest)\s+(care|support|service|contact)\s+(team|cent(re|er)|desk))",
    re.I)
INTEREST = re.compile(r"\b(interested|yes|sure|please\s+(send|share|call)|call\s+(me|us)|send\s+(it|me|us|the)|"
                      r"preview|demo|how\s+much|price|cost|rates?)\b", re.I)
AUTO_SENDER = re.compile(r"^(no-?reply|do-?not-?reply|donotreply|notifications?|alerts?|mailer|bounces?|support-?ticket)[^@]*@", re.I)
# Helpdesk and marketing systems mark their mail with their own headers.
AUTO_HEADER = re.compile(r"^(x-freshdesk|x-zendesk|x-helpscout|x-kayako|x-zoho-?desk|x-hubspot|x-mc-user|x-sfmc|list-unsubscribe|list-id)",
                         re.I)


def looks_automatic(text: str) -> bool:
    """A reply whose own words read like a machine's (receipt, ticket, survey); also usable on stored replies. A
    polite person's "thank you for your e-mail" with a yes, a no or a question in it stays a person's reply."""
    t = (text or "")[:1500]
    if AUTO_TEXT.search(t):
        return True
    return bool(AUTO_WEAK.search(t)) and not INTEREST.search(t) and not NEGATIVE.search(t)


BOUNCE_FROM = re.compile(r"(mailer-daemon|postmaster|mail\s+delivery\s+(subsystem|system)|delivery\s+status)", re.I)
BOUNCE_SUBJECT = re.compile(r"(delivery\s+status\s+notification|undeliver|delivery\s+(has\s+)?failed|mail\s+delivery\s+failed"
                            r"|returned\s+mail|failure\s+notice|address\s+not\s+found|message\s+not\s+delivered|could\s+not\s+be\s+delivered)", re.I)
QUOTE_START = re.compile(r"^(on\s.{3,200}\swrote:|-{2,}\s*original\s+message\s*-{2,}|from:\s.+|sent\s+from\s+my\s.+|_{5,}|>.*)$", re.I)
EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")


def new_text(body: str) -> str:
    """The part of a reply the person actually wrote (drop quoted history and signatures)."""
    lines = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if QUOTE_START.match(s):
            break
        lines.append(line)
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def is_auto_reply(headers: dict, subject: str) -> bool:
    auto = (headers.get("auto-submitted") or "").lower()
    if auto and auto != "no":
        return True
    if headers.get("x-autoreply") or headers.get("x-autorespond") or (headers.get("precedence") or "").lower() in ("auto_reply", "bulk", "junk"):
        return True
    if any(AUTO_HEADER.match(k) for k in headers):
        return True
    from email.utils import parseaddr

    if AUTO_SENDER.match(parseaddr(headers.get("from") or "")[1] or ""):
        return True
    return bool(AUTO_SUBJECT.search(subject or ""))


def classify_reply(subject: str, body: str, headers: dict | None = None) -> str:
    """auto | negative | positive | other"""
    headers = headers or {}
    if is_auto_reply(headers, subject):
        return "auto"
    text = new_text(body)
    if AUTO_TEXT.search(text[:1500]):
        return "auto"
    if re.search(r"\bunsubscribe\b", subject or "", re.I) or NEGATIVE.search(text) or NEGATIVE_SHORT.match(text.split("\n")[0] if text else ""):
        return "negative"
    if looks_automatic(text):
        return "auto"
    if POSITIVE.search(text):
        return "positive"
    return "other"


def is_bounce(from_addr: str, subject: str) -> bool:
    return bool(BOUNCE_FROM.search(from_addr or "")) or bool(BOUNCE_SUBJECT.search(subject or ""))


def bounced_addresses(headers: dict, body: str, known: set[str]) -> set[str]:
    """Which of our recipients a bounce message is about."""
    found = set()
    for h in ("x-failed-recipients", "final-recipient", "original-recipient"):
        for e in EMAIL_IN_TEXT.findall(headers.get(h) or ""):
            if e.lower() in known:
                found.add(e.lower())
    if not found:
        for e in EMAIL_IN_TEXT.findall(body or ""):
            if e.lower() in known:
                found.add(e.lower())
    return found


def snippet(text: str, limit: int = 300) -> str:
    one = re.sub(r"\s+", " ", text or "").strip()
    return one if len(one) <= limit else one[:limit - 1] + "…"


# A reply that clearly asks for the overview: only these get it back automatically ([auto_reply] in the config).
_ASKS = re.compile(r"^\W*(yes|yeah|yep|yup|sure|ok(ay)?|please\s+do|go\s+ahead|sounds\s+(good|great|interesting)|"
                   r"interested|send\s+(it|me|us|over|the|your)|i'?d\s+like)\b|"
                   r"\b(send|share|forward|e-?mail)\b.{0,30}\b(overview|details|info(rmation)?|brochure|pdf|it|more)\b|"
                   r"\b(yes|sure)\b.{0,15}\b(please|send)\b|\btell\s+me\s+more\b|\bmore\s+info(rmation)?\b", re.I)
_DOUBT = re.compile(r"\b(not|no|don'?t|do\s+not|never|isn'?t|aren'?t|won'?t|can'?t|cannot|already|stop|remove|"
                    r"unsubscribe|who\s+are\s+you|how\s+did\s+you)\b", re.I)


def wants_overview(text: str) -> bool:
    """True only for a plain "yes" / "send it" / "tell me more" with no doubt or refusal in it. Anything else is
    left to the owner to answer."""
    first = " ".join((new_text(text) or "").split())[:300]
    return bool(first) and bool(_ASKS.search(first)) and not _DOUBT.search(first)
