# Setting up WorldReach on the tablet (about 40 minutes, once)

It runs in **Termux**, in its own small Ubuntu, next to your two other robots. They are not touched: WorldReach
has its own folder, its own memory, its own Google Sheet, and one command of its own: `wr`.

Have ready:

| You need | Where it comes from |
|---|---|
| A new, empty **Google Sheet** | sheets.new in the browser. Name it "WorldReach". |
| Your **Google key file** (.json) | The one you already use for the India robot works: Google Cloud Console → project `review-leads` → Service accounts → `sheet-writer` → Keys → Add key → JSON. |
| **2 or 3 mailboxes** | Gmail accounts with an app password each, and/or an Outlook address (docs/OUTLOOK.md). Use mailboxes made for this, never your personal one. |
| Your **postal address** | One line. US law requires it at the end of every sales e-mail. |
| Your **WhatsApp Business number** | Shown under every e-mail. |

## Step 1 - One paste installs everything

Open Termux, paste this line (long-press → Paste), press Enter:

```
curl -fsSL https://raw.githubusercontent.com/dasravik444-cpu/worldreach/main/android/setup.sh | bash
```

Wait until it says **Done** (10-20 minutes). If it stops with an error (the internet dropped), paste the same
line again: it carries on where it stopped.

## Step 2 - The Google key and the Sheet

1. Download the key file (table above); it lands in the tablet's Download folder. Then type:
   ```
   wr getkey
   ```
   It prints an address ending in `gserviceaccount.com`.
2. Open your new Sheet → **Share** → paste that address → **Editor** → untick "Notify people" → **Share**.

## Step 3 - Your settings

```
wr settings
```

A text editor opens. Move with the arrow keys and type after each `=`:

- `WR_SHEET_ID` - from the Sheet's address, the long part between `/d/` and `/edit`
- `SENDER_NAME` - your name as businesses should see it
- `SENDER_PHONE` - your WhatsApp number with +91
- `POSTAL_ADDRESS` - your address on one line
- `MAILBOX_1_ADDRESS` and `MAILBOX_1_PASSWORD` - the first Gmail and its 16-letter app password
  (made at myaccount.google.com/apppasswords **while signed in to that Gmail**, 2-Step Verification on)
- the same for `MAILBOX_2` and `MAILBOX_3` (leave a mailbox you do not have empty)
- `MAILBOX_4_ADDRESS` and `MAILBOX_5_ADDRESS` - your two Outlook addresses; they need the steps in docs/OUTLOOK.md
  (you can add them a day later: the Gmail mailboxes work without them)

Leave `LIVE=no` for now. Save: **CTRL** then **o**, Enter. Close: **CTRL** then **x**.

## Step 4 - Check

```
wr check
```

Every line should say `[OK]`. A line with `[!!]` says what to fix (then `wr settings` again).

## Step 5 - Look at what businesses will get

```
wr preview gym
```

shows the first e-mail and the two follow-ups a gym would get (`wr preview salon`, `hotel`, ... for the others).
To change the words: tell me, or edit `[texts]` in `config/outreach.toml`.

## Step 6 - Find the first businesses

```
wr leads
```

takes the first city (Austin), about 2 hours. Keep the tablet charging and on Wi-Fi. When it is done, the
**Leads US** tab of your Sheet has the businesses. (The robot does this every day by itself once it is on.)

## Step 7 - The spam test (do not skip it)

```
wr emails --dry-run
```

fills the **Email Preview** tab with the exact e-mails that would go out now. Read a few. Then send the real first
e-mail from each of your mailboxes to **your own** addresses only:

```
wr test yourprivate@gmail.com yourother@outlook.com
```

Open both and look where each landed: **Primary** is what we want; **Spam** means that mailbox is not ready
(docs/DELIVERABILITY.md says what to do). Send me a screenshot if unsure.

## Step 8 - Go live

1. `wr settings` → change `LIVE=no` to `LIVE=yes` → save.
2. Two real e-mails with a copy to you, to see everything works:
   ```
   wr emails --max 2 --copy-to yourprivate@gmail.com
   ```
3. Switch the robot on:
   ```
   wr on
   ```

From now on it works by itself. Three Android settings keep it alive (the same as for your other robots):
**Settings → Apps → Termux → Battery → Unrestricted**, the Termux notification stays (never tap Exit), and the
tablet stays charging on Wi-Fi.

## Every day (15 minutes)

| When | What |
|---|---|
| An alert e-mail arrives | A business answered. Reply **within the hour** from the mailbox it wrote to: suggest a 15-minute call. |
| Once a day | `wr report` (or the **Replies** tab): anyone still waiting for your answer? |
| Once a day | `wr status`: is every mailbox sending? A line "SENDING PAUSED" says why and until when. |
| When the WhatsApp queue has messages | `wr whatsapp` |

## What the robot does, and when (India time)

| Time | Job |
|---|---|
| every hour at :35 | e-mails: replies and bounces read, follow-ups and new e-mails sent - only while it is office hours (8:30-16:30, Monday to Friday) at the businesses: about 19:00-6:00 India time for the US, 14:00-22:00 for the UK and Ireland |
| every hour at :20 | the follow-ups for your own clients, once you have some |
| 08:00 | lead search: the next city, about 2 hours, then the e-mail hunt |
| 11:15 | more e-mail hunting in earlier cities |
| 07:30, 07:45 | newest version (kept only if it starts cleanly); backup of the memory |

## If something is wrong

| You see | Do this |
|---|---|
| `wr: command not found` | paste the setup line of step 1 again |
| `wr status` says "not running" | `wr on`; check the battery setting |
| `[!!] Google Sheet ... 403` | share the Sheet with the key's address as Editor (step 2) |
| `the login was refused` | make a new app password for that Gmail, put it in `wr settings` |
| `SENDING PAUSED` | read the reason. It restarts by itself; `wr resume` ends it now (only if you know why it paused) |
| Anything else | `wr log 80` and send me what it shows |
