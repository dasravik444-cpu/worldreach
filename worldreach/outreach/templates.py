"""The words we send. Plain text, short, no links, no images, no prices, no tracking: what reaches inboxes and gets
answered.

What we sell (marketing/brochure.json): the follow-up a local business never has time for, done for it from its own
customer list - win back customers who stopped coming, remind the ones who are due, chase missed payments politely,
and ask happy customers for a Google review.

Each kind of business gets its own words (GROUPS). Every e-mail is put together from a few interchangeable
sentences, chosen per business by its key, so a business always gets the same wording while two businesses rarely
get identical e-mails (identical mass mail is what spam filters look for).

A text can be replaced in config/outreach.toml under [texts] (first, follow_ups, subjects, footer, auto_reply,
whatsapp_cold, whatsapp_opted_in) and [hooks] (pain / what per group). Placeholders: PLACEHOLDERS below.

Honesty rules for these texts: no invented numbers or clients, no "guarantee", nothing offered in return for a
review, and the example sums say "if" (they are sums, not results).
"""
from __future__ import annotations

import hashlib
import re
import string

from leadgen.country import PACKS

# ----------------------------------------------------------------------------------------------- per business type
GROUPS: dict[str, dict] = {
    "fitness": {
        "audience": "gyms and studios", "people": "members", "topic": "winning back past members",
        "subjects": ["past members of {business}", "{business}: members who stopped coming",
                     "a question about {business}"],
        "pain": ["Most gyms and studios have a list of members who quietly stopped coming, and nobody has the time to "
                 "write to each of them.",
                 "Every studio has members who meant to come back and never did, and a failed payment often ends a "
                 "membership without anyone noticing."],
        "what": "We do that follow-up for you: a short, friendly message series to past members, polite reminders "
                "when a payment fails, and a Google review request to members who are happy. It runs from your own "
                "member list, and there is nothing to install.",
        "math": "if {business} has 300 past members and only 5 in 100 come back, that is 15 memberships from people "
                "who already know you",
    },
    "martial": {
        "audience": "martial arts schools", "people": "students", "topic": "bringing back past students",
        "subjects": ["past students of {business}", "{business}: students who stopped training",
                     "a question about {business}"],
        "pain": ["Most schools have a list of students who stopped training after a few months, and parents who "
                 "meant to renew and forgot.",
                 "Every school loses students between belts, and unpaid fees are awkward to chase in person."],
        "what": "We do that follow-up for you: a friendly message series to past students and their parents, polite "
                "reminders for unpaid fees, and a Google review request to happy families. It runs from your own "
                "student list, and there is nothing to install.",
        "math": "if {business} has 200 past students and only 5 in 100 return, that is 10 students back on the mat",
    },
    "salon": {
        "audience": "salons and spas", "people": "clients", "topic": "bringing back clients who are overdue",
        "subjects": ["clients of {business} who are overdue", "{business}: empty chairs", "a question about {business}"],
        "pain": ["Most salons have clients who were happy, meant to rebook and simply never got round to it.",
                 "A client who is two weeks overdue rarely calls; usually it only takes one friendly reminder."],
        "what": "We send that reminder for you: a short message when a client is due for the next visit, a friendly "
                "series to the ones who have not been in for months, and a Google review request after a good "
                "appointment. It runs from your own client list, and there is nothing to install.",
        "math": "if {business} has 400 clients who have not been in for three months and 8 in 100 rebook, that is 32 "
                "appointments from people who already like you",
    },
    "food": {
        "audience": "restaurants and cafes", "people": "guests", "topic": "bringing past guests back",
        "subjects": ["past guests of {business}", "{business}: guests who came once", "a question about {business}"],
        "pain": ["Most restaurants have hundreds of guests in their booking and ordering lists who came once, liked "
                 "it, and were never invited back.",
                 "A first visit is the expensive one to win; the second usually only needs an invitation."],
        "what": "We send that invitation for you: a friendly note to guests who have not been back in a while, a "
                "thank-you with a Google review request after a visit, and a reminder before the dates that matter "
                "to you. It runs from the guest list you already have, and there is nothing to install.",
        "math": "if {business} has 1,000 past guests on its lists and 4 in 100 book again, that is 40 tables from "
                "people who already know the food",
    },
    "hotel": {
        "audience": "hotels and guesthouses", "people": "guests", "topic": "direct rebookings and reviews",
        "subjects": ["past guests of {business}", "{business}: direct bookings from past guests",
                     "a question about {business}"],
        "pain": ["Most guests who enjoyed their stay would come back or leave a review, but once they have checked "
                 "out nobody writes to them.",
                 "Past guests are the cheapest bookings a hotel can get, and they usually return through a booking "
                 "site that takes its commission."],
        "what": "We do that follow-up for you: a thank-you with a Google review request after checkout, and an "
                "invitation to past guests to book direct for their next stay. It runs from your own guest list, "
                "and there is nothing to install.",
        "math": "if {business} writes to 500 past guests and 3 in 100 book direct, that is 15 stays without a "
                "booking-site commission",
    },
    "pets": {
        "audience": "groomers and pet services", "people": "clients", "topic": "rebooking clients who are overdue",
        "subjects": ["clients of {business} who are overdue", "{business}: rebooking reminders",
                     "a question about {business}"],
        "pain": ["Most pet owners mean to rebook every six weeks and remember after ten.",
                 "Owners who were happy rarely leave a review or rebook on time unless someone reminds them."],
        "what": "We send that reminder for you: a short message when a pet is due again, a friendly series to "
                "clients who have not been back, and a Google review request after a visit. It runs from your own "
                "client list, and there is nothing to install.",
        "math": "if {business} has 300 clients who are overdue and 10 in 100 rebook, that is 30 appointments",
    },
    "auto": {
        "audience": "garages and detailers", "people": "customers", "topic": "service reminders and reviews",
        "subjects": ["customers of {business} who are due", "{business}: service reminders",
                     "a question about {business}"],
        "pain": ["Most drivers forget when the next service is due, and go wherever is nearest on the day they "
                 "remember.",
                 "Customers are happiest on the day they collect the car, and almost nobody asks them for a review "
                 "then."],
        "what": "We do that follow-up for you: a reminder when a customer is due again, a friendly note to the ones "
                "who have not been back in a year, and a Google review request after each job. It runs from your "
                "own customer list, and there is nothing to install.",
        "math": "if {business} has 600 customers who are due and 5 in 100 book, that is 30 jobs",
    },
    "default": {
        "audience": "local businesses", "people": "customers", "topic": "bringing past customers back",
        "subjects": ["past customers of {business}", "{business}: customers who came once",
                     "a question about {business}"],
        "pain": ["Most local businesses have a list of customers who were happy and simply never came back, and "
                 "nobody has the time to write to each of them.",
                 "Winning a new customer is expensive; a past customer usually only needs a friendly reminder."],
        "what": "We do that follow-up for you: a friendly message series to past customers, a reminder when someone "
                "is due again, and a Google review request to the happy ones. It runs from your own customer list, "
                "and there is nothing to install.",
        "math": "if {business} has 500 past customers and 5 in 100 come back, that is 25 sales from people who "
                "already know you",
    },
}

# Our category keys (config/shared/categories.toml) -> the wording group.
_GROUP_WORDS = {
    "martial": ("martial", "karate", "judo", "taekwondo", "jiu"),
    "fitness": ("gym", "fitness", "yoga", "pilates", "studio", "dance", "crossfit", "boxing", "climb", "swim"),
    "salon": ("salon", "barber", "beauty", "nail", "spa", "hair", "tattoo", "massage", "lash", "brow"),
    "food": ("restaurant", "cafe", "coffee", "bar", "pub", "bakery", "ice_cream", "dessert", "food"),
    "hotel": ("hotel", "guest", "bnb", "hostel", "motel", "inn", "resort", "lodg"),
    "pets": ("pet", "vet", "groom", "kennel"),
    "auto": ("auto", "garage", "car_wash", "car", "detail", "tire"),
}


def category_group(key: str) -> str:
    k = (key or "").lower()
    for group, words in _GROUP_WORDS.items():
        if any(w in k for w in words):
            return group
    return "default"


# ------------------------------------------------------------------------------------------------- the e-mails
EN = {
    "first": """{greeting}

{intro}

{pain} {what}

{cta}

{sender_first}
{footer}""",
    "follow_ups": [
        """{greeting}

A short follow-up on my note about {topic}. In plain numbers: {math}. We write the messages, you approve every word before anything goes out, and you see each answer.

{cta2}

{sender_first}
{footer}""",
        """{greeting}

Last note from me. If {topic} is not a priority for {business} right now, no problem at all, and I won't write again. If it is, reply "yes" and I'll send you the two-page overview.

All the best,
{sender_first}
{footer}""",
        """{greeting}

I said I would not write again, so only this: the offer stands whenever {topic} becomes a priority for {business}. A one-word reply is enough.

{sender_first}
{footer}""",
    ],
    "intro_usp": ['I came across {business} and liked this line on your website: "{usp}".',
                  'I was reading about {business}, and this line on your website stayed with me: "{usp}".'],
    "intro_plain": ["I came across {business} while looking at {audience} in {place}.",
                    "I found {business} while going through {audience} in {place}.",
                    "{business} came up while I was looking at {audience} in {place}."],
    "intro_noplace": ["I came across {business} while looking at {audience}.",
                      "{business} came up while I was looking at {audience}."],
    "cta": ['Would it be worth sending you a two-page overview? A one-word "yes" is enough.',
            'Shall I send you a two-page overview of how it works? Just reply "yes".',
            'Would a two-page overview be useful? A reply with "yes" is all it takes.'],
    "cta2": ['Shall I send the two-page overview? A "yes" is enough.',
             'Would you like the two-page overview? Just reply "yes".'],
    "greeting_named": ["Hi {first_name},"],
    "greeting_team": ["Hello,", "Hi there,", "Hello {business} team,"],
    # The end of every e-mail. US and Canadian law ask for the sender's postal address and a way to say no in every
    # sales e-mail; the UK and EU ask to say who writes, where the address came from and how to object.
    "footer": """{sender_business}{phone_line}
{address_line}{source_line}Not interested? Reply "no" and I won't write again.""",
    "source_line": 'I found this address on your website or public listing; reply "delete" and I erase it. ',
    "offer_line": "This e-mail is a business offer from {sender_business}. ",
    # To a business that answered "yes" / "send details": the overview, at once, in the same conversation.
    "auto_reply": """{greeting}

Thanks for getting back to me. The two-page overview is attached: what we would set up for {business}, what the messages look like, and the prices.

The easiest next step is a 15-minute call.{booking_line} Just reply with a day and time that suits you{whatsapp_line}.

{sender_first}
{sender_business}""",
    "whatsapp_cold": ("Hello {business} team, this is {sender_first} from {sender_business}. We help {audience} bring "
                      "back past {people} and collect Google reviews, done for you from your own list. May I send a "
                      "two-page overview? If you'd rather not hear from us, reply STOP."),
    "whatsapp_opted_in": ("Hi {first_name_or_there}, this is {sender_first} from {sender_business} - thanks for your "
                          "reply to my e-mail about {business}. Happy to answer any questions here, or to set up a "
                          "short call whenever suits you."),
}
LANGS = {"en": EN}

PLACEHOLDERS = {"greeting", "intro", "pain", "what", "math", "topic", "cta", "cta2", "business", "first_name",
                "first_name_or_there", "audience", "people", "place", "usp", "sender_name", "sender_first",
                "sender_business", "sender_phone", "sender_address", "sender_website", "footer", "phone_line",
                "address_line", "source_line", "booking_line", "whatsapp_line"}


class _Keep(dict):
    def __missing__(self, key):          # an unknown {placeholder} stays visible (the lint then refuses the e-mail)
        return "{" + key + "}"


def render(template: str, ctx: dict) -> str:
    text = str(template).format_map(_Keep(ctx))
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def unknown_placeholders(template: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(str(template)) if f} - PLACEHOLDERS


def pick(options, seed: str) -> str:
    """The same choice for the same business every time; different businesses get different ones."""
    if isinstance(options, str):
        return options
    if not options:
        return ""
    return options[int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % len(options)]


def tidy_address(text: str) -> str:
    """The postal address as typed in the settings, on one line, tidily."""
    parts = [re.sub(r"\s+", " ", p).strip(" ,") for p in re.split(r"[\n,]+", text or "")]
    out = ", ".join(p for p in parts if p)
    return string.capwords(out, " ") if out and out == out.lower() else out


def texts(o: dict, lang: str = "en") -> dict:
    """The language's texts with the owner's replacements ([texts] in config/outreach.toml)."""
    return {**LANGS.get(lang, EN), **{k: v for k, v in (o.get("texts") or {}).items() if v}}


def group_words(o: dict, group: str) -> dict:
    return {**GROUPS["default"], **GROUPS.get(group, {}), **((o.get("hooks") or {}).get(group) or {})}


def context(lead, o: dict, *, mailbox_name: str = "") -> dict:
    """Everything a template can use for one lead. o = the outreach config."""
    pack = PACKS.get(lead.country or "US", PACKS["US"])
    t = texts(o, pack.language)
    s = o["sender"]
    g = group_words(o, category_group(lead.category_key))
    seed = lead.key
    name = (mailbox_name or s.get("name") or "").strip()
    first = lead.first_name
    usp = re.sub(r"\s+", " ", lead.usp or "").strip().rstrip(".!?").replace('"', "'")
    place = (lead.city or lead.area or "").strip()
    address = tidy_address(s.get("postal_address", ""))
    phone = str(s.get("phone") or "").strip()
    ctx = {
        "business": lead.business, "first_name": first, "first_name_or_there": first or "there",
        "audience": g["audience"], "people": g["people"], "topic": g["topic"], "place": place, "usp": usp,
        "sender_name": name, "sender_first": name.split(" ")[0] if name else "",
        "sender_business": str(s.get("business") or "").strip(), "sender_phone": phone,
        "sender_address": address, "sender_website": str(s.get("website") or "").strip(),
        "phone_line": f"\nWhatsApp / phone: {phone}" if phone else "",
        "address_line": f"{address}\n\n" if address else "\n",
        "booking_line": "", "whatsapp_line": f", or message me on WhatsApp: {phone}" if phone else "",
    }
    if s.get("booking_link"):
        ctx["booking_line"] = f" You can pick a time here: {s['booking_link']}"
    ctx["greeting"] = render(pick(t["greeting_named"] if first else t["greeting_team"], seed + "|g"), ctx)
    if usp and 20 <= len(usp) <= 140:
        ctx["intro"] = render(pick(t["intro_usp"], seed + "|i"), ctx)
    else:
        ctx["intro"] = render(pick(t["intro_plain"] if place else t["intro_noplace"], seed + "|i"), ctx)
    ctx["pain"] = render(pick(g["pain"], seed + "|p"), ctx)
    ctx["what"] = render(g["what"], ctx)
    ctx["math"] = render(g["math"], ctx)
    ctx["cta"] = render(pick(t["cta"], seed + "|c"), ctx)
    ctx["cta2"] = render(pick(t["cta2"], seed + "|c2"), ctx)
    rules = pack.rules
    source = t["source_line"] if rules.privacy_notice else (t["offer_line"] if rules.postal_address_required else "")
    ctx["source_line"] = (render(source, ctx) + " ") if source else ""
    ctx["footer"] = render(t["footer"], ctx)
    return ctx


def subject_for(lead, o: dict) -> str:
    pack = PACKS.get(lead.country or "US", PACKS["US"])
    t = texts(o, pack.language)
    options = t.get("subjects") or group_words(o, category_group(lead.category_key))["subjects"]
    return pack.rules.subject_prefix + render(pick(options, lead.key + "|s"), {"business": lead.business})


def first_email(lead, o: dict, *, mailbox_name: str = "") -> tuple[str, str]:
    ctx = context(lead, o, mailbox_name=mailbox_name)
    return subject_for(lead, o), render(texts(o, PACKS.get(lead.country or "US", PACKS["US"]).language)["first"], ctx)


def follow_up(lead, o: dict, n: int, *, mailbox_name: str = "") -> str:
    """The n-th follow-up (1 = the first one)."""
    ctx = context(lead, o, mailbox_name=mailbox_name)
    options = texts(o, PACKS.get(lead.country or "US", PACKS["US"]).language)["follow_ups"]
    return render(options[min(n - 1, len(options) - 1)], ctx)


def auto_reply(lead, o: dict, *, mailbox_name: str = "") -> str:
    ctx = context(lead, o, mailbox_name=mailbox_name)
    return render(texts(o)["auto_reply"], ctx)


def whatsapp_text(lead, o: dict, reason: str) -> str:
    ctx = context(lead, o)
    return render(texts(o)["whatsapp_opted_in" if reason == "opted_in" else "whatsapp_cold"], ctx)
