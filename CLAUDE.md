# Working on this repository (read first)

The owner runs WorldReach on an Android tablet in Termux (8 GB RAM, shared with two other robots: Plant Parlour
`pp`, and the India review robot `robot`) and talks to you from their phone. They are not a programmer: give exact
commands to type, one per line, and say what each does. They want straight answers and no politeness padding.

- Don't make things up: check the code, test it (`python -m pytest -q`, `ruff check --select F,E9 worldreach tests`),
  and ask when something is theirs to decide. Say plainly what works, what was tested and what is still a risk.
- Never ask for app passwords, the Google key file or other secrets in chat: they type them into `wr settings`.
- Never put the owner's phone number, address or e-mail addresses into this repository (settings.txt holds them).
- This robot must never touch the other two: its own Ubuntu (`worldreach`), folder (`~/.worldreach`), job number
  (7811), boot file, and ONE Termux command (`wr`). Don't add other command names to Termux.
- WhatsApp is never automated (the app's terms; the number would be banned). Don't route around a provider's limit
  or block, and don't add tricks to dodge spam filters: the brakes in worldreach/outreach/ramp.py are the product.
- The lead finder (`leadgen/`) came from the owner's review-leads repository; keep fixes there in mind.
- The owner's plan (10 Nov 2026): 2-3 mailboxes plus one WhatsApp number; each mailbox 50, 100, 200 on the first
  three days, then slowly to 500 a day; follow-ups on day 2 and day 5; US and Europe (English-speaking first).
