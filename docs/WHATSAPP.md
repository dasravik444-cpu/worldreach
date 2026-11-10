# The WhatsApp number

**What it is for here.** In the US, the UK and Ireland almost no business publishes a WhatsApp number, and
Meta's own paid service sends no marketing messages to US numbers at all. So WhatsApp is not how we reach
businesses there. It is:

1. the number under every e-mail, so a business can write to **you** (anyone who writes first may be answered
   freely, also by the app's automatic greeting);
2. a quick way to talk to a business that answered "yes" by e-mail;
3. a first message, by hand, to the few businesses that publish a WhatsApp number themselves and that e-mail
   cannot reach (only where the country's rules allow a first message: the US, not the UK or Ireland).

**Why you press Send yourself.** WhatsApp's terms forbid automated and bulk messages, and it bans numbers that
send them, usually for good. A robot that sent the list would cost you the number within days. So the robot only
prepares a short queue (5 a day at first, slowly up to 25), and `wr whatsapp` opens each chat in WhatsApp Business
with the message typed. You press Send, come back to Termux, press Enter (or `n` = not on WhatsApp, `s` = skip,
`q` = stop). About ten seconds a message.

```
wr whatsapp              work through the queue
wr whatsapp list         only show what is waiting
wr whatsapp test +15125550100     a test message to your own number
```

Later answers ("Interested", "Not interested") you set in the **Result** column of the WhatsApp Queue tab;
"Not interested" removes the business for good.

## Set up the number (once)

1. Install **WhatsApp Business** (not the normal WhatsApp) on the tablet, or link the tablet to the phone that
   has the number (WhatsApp Business → ⋮ → Linked devices).
2. Business profile: name **Aurenflow**, the logo (`marketing/brand/aurenflow-icon.png`), category *Business
   service*, description: "Customer follow-up for local businesses: we bring back customers who stopped coming,
   remind the ones who are due, and collect Google reviews. Done for you."
3. Business tools → **Greeting message** on: "Hi, thanks for messaging Aurenflow! I'm Ravik. Tell me your business
   name and city and I'll send you a two-page overview and a time for a short call."
4. **Away message** on, outside your hours: "Thanks for your message! I'll reply within a few hours. Ravik"
5. Quick replies: `/overview` (attach the PDF), `/call` ("Would a 15-minute call this week suit you? Tell me a day
   and time, in your time zone."), `/stop` ("Understood, I won't message you again.").

## Fully automatic WhatsApp: only for our clients' customers

Meta's WhatsApp Business Platform sends automatically and legally to people **who agreed** to hear from a
business. That is the right tool for a client whose customers use WhatsApp (the UK, Europe, the Gulf), paid per
message, and a possible add-on to what we sell. It is never a way to write to strangers.
