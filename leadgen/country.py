"""Country packs: what depends on where a campaign runs.

The campaign's `[campaign] country` picks a pack when the config is loaded (`use(cfg)`); the rest of the
code reads `active()`. One process runs one campaign, so the active pack is module state; tests switch it
with `use_country()`.

Word lists that cannot do harm elsewhere (listing sites, free-mail providers, owner titles...) live in their
own modules and cover every supported country at once. A pack only holds what must differ: the language of
the websites (contact page paths, words that describe a business rather than name it), the country's
domains and postcodes, its big cities, and the rules for contacting businesses there (see docs/COMPLIANCE.md).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from .util import norm_text

# Words that say what a business is or where it is, not which one it is (all countries).
BASE_GENERIC = {
    "the", "a", "an", "and", "of", "by", "at", "in", "on", "for", "n", "amp",
    "cafe", "caf", "coffee", "tea", "restaurant", "restro", "resto", "bar", "pub", "lounge", "kitchen",
    "bistro", "diner", "eatery", "foods", "food", "house", "corner", "point", "hub", "zone", "spot",
    "bakery", "bakers", "cakes", "sweets", "family", "cuisine", "grill", "brewery",
    "hotel", "hotels", "resort", "resorts", "inn", "lodge", "guest", "stay", "suites", "residency", "palace",
    "banquet", "banquets", "hall", "halls", "venue", "venues", "lawn", "lawns", "convention", "centre", "center",
    "party", "events", "event", "management", "planner", "planners", "wedding", "weddings", "decor", "decorators",
    "decorator", "decoration", "caterers", "catering", "services", "service", "solutions", "studio", "studios",
    "interior", "interiors", "design", "designs", "designer", "designers", "architect", "architects", "associates",
    "consultants", "group", "enterprise", "enterprises", "company", "co", "ltd", "limited", "llp",
    "inc", "official", "coworking", "cowork", "space", "spaces", "office", "offices", "workspace",
    "new", "town", "park", "street", "road", "branch", "outlet", "city", "mall", "near", "opp", "opposite",
    "salon", "spa", "beauty", "hair", "nails", "nail", "barber", "barbers", "gym", "fitness",
}
BASE_HANDLE_FILLERS = {"official", "the", "its", "iam", "im", "we", "my", "our", "real", "hq", "club", "world", "by",
                       "and", "co", "inc", "ltd", "pvt", "online", "live", "daily", "original", "team", "shop", "store",
                       "page"}
BASE_CONTACT_PATHS = ("/contact", "/contact-us", "/contactus", "/contact-us/", "/about", "/about-us", "/reach-us",
                      "/get-in-touch", "/connect", "/enquiry", "/reach-us/")
BASE_POLICY_PATHS = ("/privacy-policy", "/privacy", "/terms-and-conditions", "/terms", "/refund-policy", "/disclaimer")


@dataclass(frozen=True)
class Rules:
    """How businesses in a country may be contacted (summarised from docs/COMPLIANCE.md - not legal advice).

    cold_email: "allowed"        - may be e-mailed without asking first (with the country's conditions)
                "companies_only" - only incorporated businesses (Ltd/LLP/PLC); sole traders need consent
                "published_role" - only an address the business published itself, with no "no marketing"
                                   notice, and only about something relevant to its business
                "consent_only"   - never without prior consent (letters or the business contacting us first)
    cold_whatsapp: "manual_queue" (one-tap queue of cold messages) | "opted_in" (only people who said yes)
    """
    cold_email: str
    cold_whatsapp: str
    postal_address_required: bool     # the sender's postal address must be in every commercial e-mail
    privacy_notice: bool              # GDPR Art. 14: say where the data came from and how to object
    letters: bool                     # suggest postal letters as the first contact
    contact_rule: str                 # one line for the Leads sheet: how this lead may be contacted
    law: str                          # the main rules, for notes and docs
    subject_prefix: str = ""          # put in front of every e-mail subject (Singapore: "<ADV> ")


@dataclass(frozen=True)
class Pack:
    code: str
    name: str
    language: str                     # language of the businesses' websites and of our messages
    accept_language: str
    generic_words: frozenset          # extra words that describe rather than name a business
    handle_fillers: frozenset         # extra words businesses add to social handles
    cities: frozenset                 # the country's big cities ("mentions another city")
    tlds: tuple                       # domains a business without a listed website would use
    drop_words: frozenset             # words left out when guessing a domain from a name
    postcode_re: str                  # postcode in an address (proves a found website is the same business)
    contact_paths: tuple              # contact/about paths tried directly on a business website
    policy_paths: tuple               # legal pages read by the deeper e-mail hunt
    rules: Rules
    local_abbrevs: tuple = ()          # short forms of the home city used in handles ("kol" for Kolkata)
    region_words: frozenset = field(default_factory=frozenset)   # filled by use(): the campaign's place names
    other_cities: frozenset = field(default_factory=frozenset)   # filled by use(): big cities minus the campaign's own


_IN = Pack(
    code="IN", name="India", language="en", accept_language="en-IN,en;q=0.9",
    generic_words=frozenset({"chai", "dhaba", "biryani", "multicuisine", "pvt", "private", "india", "indian", "kolkata",
                             "calcutta", "howrah", "salt", "lake", "sector", "newtown", "rajarhat", "centre1", "centre2",
                             "west", "bengal"}),
    handle_fillers=frozenset({"kol", "kolkata", "calcutta", "cal", "ccu", "india", "in", "wb", "bengal", "west"}),
    cities=frozenset({"delhi", "new delhi", "mumbai", "bombay", "bangalore", "bengaluru", "chennai", "hyderabad", "pune",
                      "ahmedabad", "jaipur", "lucknow", "noida", "gurgaon", "gurugram", "chandigarh", "bhubaneswar",
                      "guwahati", "patna", "ranchi", "indore", "surat", "kochi", "goa", "dubai", "london", "singapore",
                      "dhaka", "kathmandu", "siliguri", "durgapur", "asansol"}),
    tlds=(".com", ".in", ".co.in"),
    drop_words=frozenset({"pvt", "private", "india", "kolkata", "calcutta"}),
    postcode_re=r"\b[1-9]\d{2}\s?\d{3}\b",
    contact_paths=BASE_CONTACT_PATHS, policy_paths=BASE_POLICY_PATHS,
    local_abbrevs=("kol",),
    rules=Rules(cold_email="allowed", cold_whatsapp="manual_queue", postal_address_required=False, privacy_notice=False,
                letters=False,
                contact_rule="E-mail OK (say who you are, honour 'no'); WhatsApp one by one",
                law="India: no cold e-mail law for businesses; TRAI rules cover calls/SMS; DPDP Act phases in by 2027"),
)

_DE = Pack(
    code="DE", name="Germany", language="de", accept_language="de-DE,de;q=0.9,en;q=0.7",
    generic_words=frozenset({
        "gaststätte", "gaststaette", "gasthaus", "gasthof", "wirtshaus", "kneipe", "kaffee", "kaffeehaus", "konditorei",
        "bäckerei", "baeckerei", "backhaus", "backstube", "imbiss", "döner", "doener", "kebab", "kebap", "pizzeria",
        "ristorante", "trattoria", "osteria", "brasserie", "brauhaus", "biergarten", "weinbar", "weinstube", "stube",
        "eck", "ecke", "haus", "hof", "küche", "kueche", "friseur", "frisör", "frisoer", "haarstudio", "barbershop",
        "kosmetik", "kosmetikstudio", "nagelstudio", "fitnessstudio", "sportstudio", "pension", "eiscafe", "eiscafé",
        "eisdiele", "gmbh", "ug", "kg", "ohg", "gbr", "ek", "inh", "inhaber", "und", "der", "die", "das", "zum", "zur",
        "am", "im", "bei", "von", "vom", "mit", "deutschland", "germany", "filiale", "str", "strasse", "straße"}),
    handle_fillers=frozenset({"de", "deutschland", "germany", "ger"}),
    cities=frozenset({"berlin", "hamburg", "münchen", "muenchen", "munich", "köln", "koeln", "cologne", "frankfurt",
                      "stuttgart", "düsseldorf", "duesseldorf", "dortmund", "essen", "leipzig", "bremen", "dresden",
                      "hannover", "nürnberg", "nuernberg", "nuremberg", "duisburg", "bochum", "wuppertal", "bielefeld",
                      "bonn", "münster", "muenster", "mannheim", "karlsruhe", "augsburg", "wiesbaden", "potsdam",
                      "wien", "vienna", "zürich", "zurich", "istanbul", "london", "paris"}),
    tlds=(".de", ".com", ".berlin", ".eu"),
    drop_words=frozenset({"gmbh", "ug", "haftungsbeschrankt", "haftungsbeschraenkt", "kg", "ohg", "gbr", "ek", "e", "k",
                          "inh", "inhaber", "und", "zum", "zur", "am", "im", "der", "die", "das", "deutschland"}),
    postcode_re=r"\b\d{5}\b",
    contact_paths=BASE_CONTACT_PATHS + ("/kontakt", "/kontakt/", "/impressum", "/impressum/", "/ueber-uns", "/uber-uns",
                                        "/anfahrt"),
    policy_paths=BASE_POLICY_PATHS + ("/datenschutz", "/datenschutzerklaerung", "/agb"),
    rules=Rules(cold_email="consent_only", cold_whatsapp="opted_in", postal_address_required=True, privacy_notice=True,
                letters=True,
                contact_rule="Letter only (no cold e-mail/WhatsApp - UWG §7); e-mail once they ask",
                law="Germany: UWG §7(2) - advertising e-mails/messages to businesses need prior express consent; "
                    "letters are allowed unless the business objected; GDPR Art. 14 notice on first contact"),
)

_US = Pack(
    code="US", name="United States", language="en", accept_language="en-US,en;q=0.9",
    generic_words=frozenset({"llc", "corp", "usa", "america", "american", "ave", "blvd", "st"}),
    handle_fillers=frozenset({"usa", "us", "nyc", "la", "atx", "chi", "sf"}),
    cities=frozenset({"new york", "nyc", "los angeles", "chicago", "houston", "phoenix", "philadelphia", "san antonio",
                      "san diego", "dallas", "austin", "jacksonville", "san jose", "fort worth", "columbus", "charlotte",
                      "indianapolis", "san francisco", "seattle", "denver", "nashville", "boston", "las vegas",
                      "portland", "miami", "atlanta"}),
    tlds=(".com", ".net", ".us"),
    drop_words=frozenset({"llc", "corp", "usa"}),
    postcode_re=r"\b\d{5}(?:-\d{4})?\b",
    contact_paths=BASE_CONTACT_PATHS, policy_paths=BASE_POLICY_PATHS,
    rules=Rules(cold_email="allowed", cold_whatsapp="manual_queue", postal_address_required=True, privacy_notice=False,
                letters=False,
                contact_rule="E-mail OK (CAN-SPAM: your postal address + opt-out); WhatsApp only a number it publishes",
                law="USA: CAN-SPAM - truthful sender/subject, a valid postal address and a working opt-out honoured "
                    "within 10 business days; automated texts need consent (TCPA), so WhatsApp goes one by one, by hand, "
                    "only to numbers the business publishes as WhatsApp"),
)

_GB = Pack(
    code="GB", name="United Kingdom", language="en", accept_language="en-GB,en;q=0.9",
    generic_words=frozenset({"uk", "england", "plc"}),
    handle_fillers=frozenset({"uk", "ldn", "mcr", "england"}),
    cities=frozenset({"london", "manchester", "birmingham", "leeds", "glasgow", "liverpool", "bristol", "sheffield",
                      "edinburgh", "cardiff", "leicester", "nottingham", "newcastle", "brighton", "belfast", "york",
                      "oxford", "cambridge"}),
    tlds=(".co.uk", ".com", ".uk"),
    drop_words=frozenset({"uk", "plc"}),
    postcode_re=r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b",
    contact_paths=BASE_CONTACT_PATHS, policy_paths=BASE_POLICY_PATHS,
    rules=Rules(cold_email="companies_only", cold_whatsapp="opted_in", postal_address_required=False, privacy_notice=True,
                letters=True,
                contact_rule="E-mail OK only if a company (Ltd/LLP/PLC); sole traders: letter",
                law="UK: PECR reg. 22 - e-mail marketing to sole traders/partnerships needs consent, limited companies "
                    "may be e-mailed with identification and an opt-out; UK GDPR Art. 14 notice"),
)

_AU = Pack(
    code="AU", name="Australia", language="en", accept_language="en-AU,en;q=0.9",
    generic_words=frozenset({"pty", "australia", "aussie"}),
    handle_fillers=frozenset({"au", "aus", "syd", "mel", "melb", "bne"}),
    cities=frozenset({"sydney", "melbourne", "brisbane", "perth", "adelaide", "gold coast", "canberra", "newcastle",
                      "hobart", "darwin", "geelong", "cairns"}),
    tlds=(".com.au", ".com", ".au"),
    drop_words=frozenset({"pty", "australia"}),
    postcode_re=r"\b\d{4}\b",
    contact_paths=BASE_CONTACT_PATHS, policy_paths=BASE_POLICY_PATHS,
    rules=Rules(cold_email="published_role", cold_whatsapp="opted_in", postal_address_required=False, privacy_notice=False,
                letters=False,
                contact_rule="E-mail its published address only (no 'no marketing' notice); opt-out in every e-mail",
                law="Australia: Spam Act 2003 - consent may be inferred from a conspicuously published business address "
                    "when the message relates to the business and no 'no unsolicited e-mail' statement is published"),
)

# English-speaking markets beyond the first four. Their rules come from background knowledge, not from the
# research in docs/COMPLIANCE.md - check before a large campaign there.
_CA = Pack(
    code="CA", name="Canada", language="en", accept_language="en-CA,en;q=0.9",
    generic_words=frozenset({"canada", "canadian", "ltee", "inc"}),
    handle_fillers=frozenset({"ca", "can", "yyz", "yvr", "yul", "the6ix"}),
    cities=frozenset({"toronto", "montreal", "vancouver", "calgary", "edmonton", "ottawa", "winnipeg", "quebec city",
                      "hamilton", "kitchener", "victoria", "halifax", "mississauga", "brampton", "surrey", "markham"}),
    tlds=(".ca", ".com"),
    drop_words=frozenset({"inc", "ltd", "ltee", "canada"}),
    postcode_re=r"\b[A-Z]\d[A-Z][ -]?\d[A-Z]\d\b",
    contact_paths=BASE_CONTACT_PATHS, policy_paths=BASE_POLICY_PATHS,
    rules=Rules(cold_email="published_role", cold_whatsapp="opted_in", postal_address_required=True, privacy_notice=False,
                letters=False,
                contact_rule="E-mail its published address only, about its business (CASL); your address + unsubscribe",
                law="Canada: CASL - implied consent from a conspicuously published business address when the message is "
                    "about the recipient's business and no 'no unsolicited messages' statement is published; every message "
                    "needs your name, mailing address and an unsubscribe honoured within 10 business days"),
)

_IE = Pack(
    code="IE", name="Ireland", language="en", accept_language="en-IE,en;q=0.9",
    generic_words=frozenset({"ireland", "irish", "eire", "teoranta", "dac"}),
    handle_fillers=frozenset({"ie", "irl", "dub"}),
    cities=frozenset({"dublin", "cork", "limerick", "galway", "waterford", "kilkenny", "drogheda", "dundalk", "bray",
                      "sligo", "athlone", "killarney", "wexford"}),
    tlds=(".ie", ".com"),
    drop_words=frozenset({"ltd", "dac", "teoranta", "ireland"}),
    postcode_re=r"\b[AC-FHKNPRTV-Y]\d{2}\s?[AC-FHKNPRTV-Y\d]{4}\b",
    contact_paths=BASE_CONTACT_PATHS, policy_paths=BASE_POLICY_PATHS,
    rules=Rules(cold_email="companies_only", cold_whatsapp="opted_in", postal_address_required=False, privacy_notice=True,
                letters=True,
                contact_rule="E-mail OK only if a company (Ltd/DAC/PLC); sole traders: letter",
                law="Ireland: S.I. 336/2011 reg. 13 - e-mail marketing to individuals (incl. sole traders) needs consent; "
                    "company addresses may be e-mailed about their business with an opt-out; GDPR Art. 14 notice"),
)

_NZ = Pack(
    code="NZ", name="New Zealand", language="en", accept_language="en-NZ,en;q=0.9",
    generic_words=frozenset({"nz", "zealand", "aotearoa", "kiwi"}),
    handle_fillers=frozenset({"nz", "akl", "wlg", "chch"}),
    cities=frozenset({"auckland", "wellington", "christchurch", "hamilton", "tauranga", "dunedin", "napier", "nelson",
                      "queenstown", "rotorua", "palmerston north", "new plymouth"}),
    tlds=(".co.nz", ".nz", ".com"),
    drop_words=frozenset({"ltd", "nz", "limited"}),
    postcode_re=r"\b\d{4}\b",
    contact_paths=BASE_CONTACT_PATHS, policy_paths=BASE_POLICY_PATHS,
    rules=Rules(cold_email="published_role", cold_whatsapp="opted_in", postal_address_required=False, privacy_notice=False,
                letters=False,
                contact_rule="E-mail its published address only, about its business; unsubscribe in every e-mail",
                law="New Zealand: Unsolicited Electronic Messages Act 2007 - consent may be inferred from a conspicuously "
                    "published business address when the message relates to the business; identify the sender and "
                    "offer a working unsubscribe"),
)

_AE = Pack(
    code="AE", name="United Arab Emirates", language="en", accept_language="en-AE,en;q=0.9",
    generic_words=frozenset({"uae", "emirates", "fze", "fzco", "fz", "trading", "est", "establishment"}),
    handle_fillers=frozenset({"uae", "dxb", "auh", "shj"}),
    cities=frozenset({"dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah", "fujairah", "al ain", "umm al quwain"}),
    tlds=(".ae", ".com"),
    drop_words=frozenset({"llc", "fze", "fzco", "uae", "trading", "est"}),
    postcode_re=r"(?!x)x",            # the UAE has no postcodes
    contact_paths=BASE_CONTACT_PATHS, policy_paths=BASE_POLICY_PATHS,
    rules=Rules(cold_email="allowed", cold_whatsapp="manual_queue", postal_address_required=False, privacy_notice=False,
                letters=False,
                contact_rule="E-mail OK (say who you are, honour 'no'); WhatsApp one by one",
                law="UAE: no specific cold e-mail rule for businesses found (not researched in depth); the PDPL protects "
                    "personal data - keep messages relevant, identify yourself and honour every opt-out"),
)

_SG = Pack(
    code="SG", name="Singapore", language="en", accept_language="en-SG,en;q=0.9",
    generic_words=frozenset({"singapore", "sg", "pte"}),
    handle_fillers=frozenset({"sg", "sgp"}),
    cities=frozenset({"singapore"}),
    tlds=(".sg", ".com.sg", ".com"),
    drop_words=frozenset({"pte", "ltd", "singapore", "sg"}),
    postcode_re=r"\b\d{6}\b",
    contact_paths=BASE_CONTACT_PATHS, policy_paths=BASE_POLICY_PATHS,
    rules=Rules(cold_email="allowed", cold_whatsapp="opted_in", postal_address_required=False, privacy_notice=False,
                letters=False,
                contact_rule="E-mail OK with <ADV> in the subject and an unsubscribe (Spam Control Act)",
                law="Singapore: Spam Control Act - unsolicited commercial e-mail sent in bulk must start its subject with "
                    "<ADV>, give the sender's contact details and a working unsubscribe; calls/texts: check the Do Not Call "
                    "registry (PDPA)",
                subject_prefix="<ADV> "),
)

PACKS = {p.code: p for p in (_IN, _DE, _US, _GB, _AU, _CA, _IE, _NZ, _AE, _SG)}
SUPPORTED = tuple(PACKS)

_active: Pack = _IN
_cache: dict = {}


def active() -> Pack:
    return _active


def place_words(name: str, aliases=()) -> set[str]:
    """Normalised words of the campaign's place names ("Berlin", "Kolkata", "New York")."""
    out: set[str] = set()
    for n in [name, *aliases]:
        t = norm_text(n)
        if t:
            out.add(t)
            out |= {w for w in t.split() if len(w) >= 3}
    return out


def use_country(code: str, place: str = "", aliases=()) -> Pack:
    """Activate a pack for a campaign in `place` (its name and aliases count as local words)."""
    global _active
    _cache.clear()
    base = PACKS.get((code or "").upper())
    if base is None:
        raise ValueError(f"country '{code}' is not supported (supported: {', '.join(SUPPORTED)})")
    local = place_words(place, aliases)
    _active = replace(base, region_words=frozenset(local),
                      other_cities=frozenset(c for c in base.cities if norm_text(c) not in local))
    return _active


def use(cfg) -> Pack:
    a = cfg["area"]
    return use_country(cfg["campaign"].get("country", "IN"), a.get("name") or "", a.get("aliases") or [])


def generic_words() -> frozenset:
    """Words that describe rather than name a business here (cached: called for every name comparison)."""
    if "generic" not in _cache:
        p = active()
        _cache["generic"] = frozenset(BASE_GENERIC | p.generic_words | p.region_words)
    return _cache["generic"]


def handle_fillers() -> frozenset:
    if "fillers" not in _cache:
        p = active()
        _cache["fillers"] = frozenset(BASE_HANDLE_FILLERS | p.handle_fillers | {w.replace(" ", "") for w in p.region_words})
    return _cache["fillers"]


def contact_rule(legal_kind: str = "", objects_to_advertising: bool = False) -> str:
    """One line for the Leads sheet: how this business may be contacted here (see docs/COMPLIANCE.md)."""
    r = active().rules
    if objects_to_advertising:
        return "Do not contact: its website objects to advertising"
    if r.cold_email == "companies_only":
        if legal_kind == "company":
            return "E-mail OK (limited company): say who you are, opt-out in every e-mail"
        return "No cold e-mail (sole trader or unknown): letter, or wait until they contact you"
    return r.contact_rule


def postcodes(text: str) -> set[str]:
    return {re.sub(r"\s+", "", m.upper()) for m in re.findall(active().postcode_re, text or "", re.I)}


# Until a campaign config is loaded, the original India pack is active (offline tools and tests).
use_country("IN")
