# You won a client: running their follow-ups

Everything for a client lives in one folder on the tablet, `clients-data/<name>/`, which is never uploaded
anywhere (it holds the client's customer list).

## 1. Set the client up (15 minutes)

```
wr client new lotus-yoga
```

makes `clients-data/lotus-yoga/client.toml`. Open it (it is inside the robot's folder; ask me and I will give you
the exact line to type for your tablet) and fill in:

- `name` - the business as its customers know it; `sender_name` - who signs ("Maria at Lotus Yoga")
- `address` - the business's postal address (required in marketing e-mails)
- `review_link` - its Google review link (the client finds it in Google Business Profile → "Ask for reviews")
- `notify_email` - the client's e-mail: customers' replies also go there
- `timezone` - the client's
- `[words] visit` - "class", "stay", "appointment", "cut" ...
- which follow-ups run (`[campaigns]`), and after how many days

## 2. The client's list

Ask the client for an export from their booking or membership system (every system has one; a spreadsheet is
fine) with these columns, in any order and under any of the usual names:

| Column | Example | Needed for |
|---|---|---|
| name | Maria Lopez | the greeting |
| email | maria@example.com | everything |
| last visit | 2026-11-03 | deciding who is due for what |
| consent | yes | marketing follow-ups go only to "yes" |
| unpaid (optional) | $49 | payment reminders |

Save it as `clients-data/lotus-yoga/customers.csv`. Whenever the client sends a fresh export, replace the file:
the tool notices who has come back since (their last visit moved forward) and counts it.

## 3. Show the client the exact words, and get a yes

```
wr client preview lotus-yoga
```

shows who would get which message today and the exact text. Send the texts to the client. **Nothing goes out
until** the client has approved them and you set `approved = true` in `client.toml`.

## 4. It runs

The robot runs every approved client each hour (`wr client run --all`), inside the client's own hours (9-18),
at most `daily_limit` messages a day, one follow-up per customer at a time and at most one message a week.

Use a mailbox made for the client's messages (`mailbox = 4`, say), not one that sends cold e-mails: the two kinds
of mail should never share a reputation. Best of all is the client's own mailbox (their Gmail with an app
password, added as one of your `MAILBOX_n`).

## 5. The monthly report

```
wr client report lotus-yoga
```

Messages sent by kind, who answered and what they wrote, who came back after a note, who asked to stop. That is
the report the brochure promises: send it to the client every month.

## What is honest to promise today

| In the brochure | State |
|---|---|
| Review requests, come-back reminders, win-back series, payment reminders **by e-mail** | built and tested |
| "You approve every message", "every answer comes to you", monthly report | built |
| Print-ready QR code for reviews | make it from the review link with any QR tool (or ask me for a card) |
| Text messages (SMS), WhatsApp to customers | **not built**: an add-on to set up per client (US: registered sender needed) |
| Follow-up to new enquiries, birthday notes (the "Complete" plan) | **not built yet**: tell me when the first client wants them |
