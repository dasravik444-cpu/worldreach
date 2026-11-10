"""A spam-filter's eye on our own e-mails, before any is sent ( wr check ,  wr preview ).

No tool can promise the inbox: Gmail and Outlook judge mostly by how recipients react (replies, deletes, "report
spam") and by the sending account's history. What can be checked in the text itself is the list below: the things
filters and people both read as a mass mailing.
"""
from __future__ import annotations

import re

# Words that mark a mass sales mailing. Deliberately short: the classic triggers, not every sales word.
TRIGGERS = [
    "100% free", "act now", "apply now", "buy now", "cash bonus", "click here", "click below", "congratulations",
    "double your", "earn money", "extra income", "free trial", "guarantee", "guaranteed", "increase sales",
    "limited time", "lowest price", "make money", "million", "no obligation", "offer expires", "once in a lifetime",
    "order now", "risk-free", "risk free", "special promotion", "this isn't spam", "urgent", "winner",
    "you have been selected", "no cost", "best price", "cheap", "discount", "amazing", "incredible", "revolutionary",
    "skyrocket", "explode your", "10x",
]
URL = re.compile(r"(https?://|www\.)\S+|\b[\w-]+\.(com|net|org|io|co|ai|app|ly|me)(/\S*)?\b", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
SHOUT = re.compile(r"\b[A-Z]{4,}\b")
MAX_WORDS_FIRST, MAX_WORDS_FOLLOW_UP = 130, 90
MAX_SUBJECT_CHARS = 60


def words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def body_without_footer(body: str, footer: str = "") -> str:
    return body.replace(footer, "") if footer else body


def lint(subject: str, body: str, *, footer: str = "", follow_up: bool = False, allow_shout: tuple = ("STOP",)) -> list[str]:
    """Warnings for one rendered e-mail (the footer, which holds our own address and phone, is not judged)."""
    out: list[str] = []
    main = body_without_footer(body, footer)
    low = f"{subject}\n{main}".lower()
    hits = [w for w in TRIGGERS if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", low)]
    if hits:
        out.append("spam-filter words: " + ", ".join(sorted(set(hits))))
    links = [m.group(0) for m in URL.finditer(EMAIL.sub(" ", main))]
    if links:
        out.append(f"contains a link ({links[0]}): cold e-mails with links land in spam and Promotions more often")
    if "{" in body or "}" in body or "{" in subject:
        out.append("an unfilled {placeholder} is left in the text")
    n = words(main)
    most = MAX_WORDS_FOLLOW_UP if follow_up else MAX_WORDS_FIRST
    if n > most:
        out.append(f"{n} words: keep it under {most} (short e-mails get more replies)")
    if len(subject) > MAX_SUBJECT_CHARS:
        out.append(f"the subject has {len(subject)} characters: keep it under {MAX_SUBJECT_CHARS}")
    if subject and subject == subject.upper() and any(c.isalpha() for c in subject):
        out.append("the subject is all capitals")
    shouts = [w for w in SHOUT.findall(main) if w not in allow_shout]
    if len(shouts) > 1:
        out.append("words in capitals: " + ", ".join(sorted(set(shouts))[:5]))
    if main.count("!") > 1 or "!" in subject:
        out.append("exclamation marks: at most one, none in the subject")
    if re.search(r"[$€£]\s?\d|\d\s?(usd|dollars)\b", low):
        out.append("a price in a cold e-mail: prices belong in the answer to someone who asked")
    if not follow_up and "?" not in main:
        out.append("no question: end with one easy question to answer")
    return out
