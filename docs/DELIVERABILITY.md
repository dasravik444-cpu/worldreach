# Staying out of the spam folder

Nobody can promise the inbox. Gmail and Outlook decide mostly by **how recipients react** (replies are good;
deletes without reading and "Report spam" are bad) and by the **history of the sending mailbox**. What a system
can do is avoid everything that is known to hurt, notice trouble at once, and stop before a mailbox is lost.

## What WorldReach does by itself

| What | Why |
|---|---|
| Plain text, short, **no links, images, tracking pixels or attachments** in cold e-mails | These are what filters score first. The overview PDF goes only to businesses that asked for it. |
| Every e-mail is put together from interchangeable sentences, per business | Identical mass mail is what filters look for. `wr check` and `wr preview` also scan our own words for spam-filter triggers. |
| One easy question at the end ("reply yes") | Replies are the strongest good signal there is. |
| Sends only in the business's own office hours, a few minutes apart, mailboxes taking turns | Mail at 3 a.m. in bursts looks like a machine. |
| **Warm-up**: 50, 100, 200, then up to 500 a day per Gmail mailbox; Outlook starts at 20 | A mailbox that jumps to hundreds is stopped. A step is only taken after a day that went well, and never more than about double the best recent day. |
| **Address check** before a first e-mail: mistyped domains, dead mailboxes (noreply@, postmaster@), throw-away services, domains without a mail server | Every bounce costs reputation. Above about 3% bounces, mail starts landing in spam. |
| **Bounce brake**: from 3% the limit stops rising; from 6% that mailbox pauses 12 hours and drops a step | A bad batch of addresses must not burn the mailbox. |
| **Provider brake**: "daily limit" pauses that mailbox until tomorrow and holds it under that level for a week; "blocked as spam" pauses it two days and halves it | Carrying on after a warning is how accounts are suspended. |
| Never more than 480 in any 24 hours from a Gmail mailbox (280 from Outlook) | Gmail's own ceiling is 500 in any 24 hours, including your own replies. |
| Follow-ups in the same conversation, at most two, and any reply ends them | People report the fourth chaser, not the first note. |
| "No" / "unsubscribe" / "stop" removes the business for good, from every mailbox; an unsubscribe header in every e-mail | Complaints are counted against the mailbox (Gmail's line is 0.3%, and trouble starts near 0.1%). |
| Each business gets e-mail from exactly one mailbox, once | Two mailboxes writing to the same person looks like a ring. |

## What only you can do

1. **Mailboxes made for this**, never your personal one. Give each a real name and a profile photo, switch on
   2-Step Verification, and use it like a person for a few days first: send and answer a few real e-mails.
2. **Run the spam test** before going live and after every change of the words:
   `wr test yourprivate@gmail.com yourother@outlook.com` and look where each mailbox's e-mail landed. For a score
   out of 10, add the address that mail-tester.com shows you.
3. **Answer replies within the hour**, from the mailbox that got them. Conversations are the best warm-up there is.
4. **Watch `wr status`** in the first two weeks: bounces under 3%, no pauses.
5. **Never buy a list** and never switch on guessed addresses (`include_unverified`): both bounce.

## The honest limits of free Gmail addresses

- Google's rules for Gmail forbid unsolicited bulk mail. A free @gmail.com address that sends hundreds of cold
  e-mails a day can be limited or suspended whatever we do; people who do this for a living send **30-50 a day
  per mailbox** and use many mailboxes. Your plan (up to 500 a day per mailbox) is the fast lane: it can work for
  a while, and it can cost a mailbox. The brakes are there to make that loss rare and early, not impossible.
- The e-mails come from "@gmail.com", which some business mail systems trust less than a company address.

## The upgrade that helps most (when the first money comes in)

**Your own domain with business mailboxes**: a domain like `aurenflow-mail.com` (about $12 a year) and 3-5
mailboxes on Google Workspace or Microsoft 365 (about $6-7 a month each), with SPF, DKIM and DMARC switched on
(`wr dns yourdomain.com` checks them). Add each as `MAILBOX_n=smtp` (Workspace: `smtp.gmail.com` /
`imap.gmail.com` with an app password) or `outlook`. Benefits: a company address businesses trust, far higher
provider limits, and a reputation that is yours and not shared with every other Gmail user. Use a separate domain
from your main website's, so trouble with cold e-mail never touches your main address.

## Reading the numbers

`wr report` shows e-mails per day, bounces and replies. Whether an e-mail was opened cannot be counted: that needs
a tracking pixel, which sends e-mails to spam. As a rough guide from published 2026 figures (they vary a lot by
source): 1-5 replies per 100 businesses is normal for cold e-mail to small local businesses, and most replies come
from the first e-mail and the first follow-up. Judge the words by replies per 100 over at least 500 businesses,
then change one thing at a time.
