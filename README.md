# WorldReach

Finds local businesses abroad (United States, United Kingdom, Ireland), writes to them from several mailboxes, and
runs the follow-up service we sell them. It runs by itself on an Android tablet (Termux), next to the two India
robots, without touching them.

**What we sell** (brand: Aurenflow, [the two-page overview](marketing/brochure.pdf)): the follow-up a local
business never has time for, done from its own customer list - win back customers who stopped coming, remind the
ones who are due, chase missed payments politely, and ask happy customers for a Google review. For gyms and
studios, martial arts schools, salons and spas, hotels, restaurants, groomers and garages.

| Part | What it does |
|---|---|
| **Lead finder** (`leadgen/`) | Businesses of these kinds, city by city, from open map data (Overture Maps, OpenStreetMap) and their own websites. Only businesses with an e-mail address or a published WhatsApp number go into the Google Sheet. |
| **Mailboxes** (`worldreach/mail/`) | Up to 6: Gmail (app password), Outlook / Hotmail (Microsoft sign-in), or a mailbox on your own domain. |
| **Sending engine** (`worldreach/outreach/`) | Every hour, in each business's own office hours: reads replies and bounces, sends follow-ups (day 2 and day 5) and new e-mails. Each mailbox warms up by itself (50, 100, 200 ... 500 a day) and stops by itself when something goes wrong. A plain "yes" gets the overview PDF back at once. |
| **WhatsApp queue** | Messages for you to send with one tap (never by a machine: WhatsApp bans that). |
| **Client follow-ups** (`worldreach/clients/`) | The service itself: review requests, come-back reminders, win-back notes and payment reminders to a client's customers. |
| **Robot** (`worldreach/robot.py`) | The timetable: e-mails hourly, lead search daily, updates, backups. |

| Read | For |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | **start here**: the tablet, step by step |
| [docs/OUTLOOK.md](docs/OUTLOOK.md) | adding an Outlook / Hotmail mailbox |
| [docs/HOSTING.md](docs/HOSTING.md) | tablet or online server: which, when, and how to move |
| [docs/DELIVERABILITY.md](docs/DELIVERABILITY.md) | staying out of the spam folder: what the system does, what you must do, the honest limits |
| [docs/COMPLIANCE.md](docs/COMPLIANCE.md) | the rules per country, and which European countries can be written to |
| [docs/WHATSAPP.md](docs/WHATSAPP.md) | the WhatsApp number |
| [docs/CLIENTS.md](docs/CLIENTS.md) | you won a client: running their follow-ups |

## The commands (on the tablet: `wr ...`)

```
wr on / wr off        the robot
wr status             mailboxes (warm-up, pauses), leads, e-mails, replies
wr check              test the settings, the Sheet, every mailbox and our own e-mails
wr preview gym        show the e-mails a gym would get
wr test a@x b@y       spam test: the next first e-mail from every mailbox, only to your own addresses
wr emails --dry-run   prepare the e-mails into the Sheet's "Email Preview" tab, send nothing
wr report             e-mails per day, bounces, replies, who is waiting for your answer
wr whatsapp           today's WhatsApp messages, one tap each
wr client ...         the follow-ups we run for a client
```

## For development

```
pip install -r requirements.txt pytest ruff
python -m pytest -q                 # all tests, offline (pretend mailboxes, pretend Sheet, pretend internet)
python scripts/simulate.py          # weeks of sending against pretend mailboxes
python -m worldreach preview        # the e-mails, with the text check
python marketing/build_brochure.py  # the PDF (needs node + Playwright + Chromium)
python scripts/make_markets.py      # the city files, after editing the city lists
```

Lead data, the outreach memory, clients' customer lists, keys and settings never go into git (`.gitignore`).

## For website owners: WorldReachBot

`WorldReachBot` reads the public contact pages of local businesses (home, contact, about; at most a handful of
pages per site, a few seconds apart). It says who it is and follows your `robots.txt`. To keep it out:

```
User-agent: WorldReachBot
Disallow: /
```

To have your business's details removed, open an issue here or reply "delete" to any e-mail from us. We erase
them and never write again.

Contains data from the Overture Maps Foundation (CDLA-Permissive-2.0) and © OpenStreetMap contributors (ODbL).
