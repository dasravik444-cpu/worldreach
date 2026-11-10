# Adding an Outlook / Hotmail mailbox

Microsoft no longer lets a program sign in to an outlook.com mailbox with a password or an app password
(switched off in September 2024). The mailbox has to be opened once, by you, in the browser. For that Microsoft
wants a free "app registration": a note in your Microsoft account that says a program of yours may send and read
mail. It takes about ten minutes, once, and covers all your Outlook mailboxes.

**Honest warnings first**

- A new outlook.com account may send very little at first (Microsoft gives no number; people report 10-50 a day
  for the first days or weeks), and about 300 a day once trusted. WorldReach therefore starts an Outlook mailbox at
  20 a day and stops at 280. It is a useful second or third mailbox, not a replacement for Gmail.
- This part could not be tried against Microsoft's real servers from where it was written (only against a
  stand-in). Your first `wr outlook-login` is the real test: if anything on the screens below looks different,
  send me a screenshot.

## 1. The app registration (once)

1. In the browser open **entra.microsoft.com** and sign in with a Microsoft account (the Outlook address is fine).
   If it says you have no directory, open **azure.microsoft.com/free** first and create the free account (it asks
   for a phone number, and may ask for a card to check who you are; nothing is charged).
2. Left menu: **Applications → App registrations → New registration**.
3. Name: `WorldReach`. Supported account types: **Accounts in any organizational directory and personal Microsoft
   accounts**. Redirect URI: leave empty. **Register**.
4. On the page that opens, copy the **Application (client) ID** (a long code with dashes).
5. Left: **Authentication** → scroll to **Advanced settings** → **Allow public client flows: Yes** → **Save**.
6. Left: **API permissions → Add a permission → Microsoft Graph → Delegated permissions** → tick **Mail.Send**,
   **Mail.ReadWrite** and **offline_access** → **Add permissions**.

## 2. The settings

```
wr settings
```

```
MAILBOX_3=outlook
MAILBOX_3_ADDRESS=yourname@outlook.com
OUTLOOK_CLIENT_ID=the-code-you-copied
```

Save (CTRL o, Enter, CTRL x).

## 3. Sign in (once per Outlook mailbox)

```
wr outlook-login 3
```

It shows a web address and a short code. Open the address in the browser, type the code, sign in **as that Outlook
address**, tap **Accept**. Termux then says "Signed in". The sign-in is kept on the tablet (`secrets/`) and renews
by itself; if Microsoft ever ends it, `wr status` says so and you run the command again.

## 4. Check

```
wr check
wr test yourprivate@gmail.com
```

## Microsoft 365 (a paid mailbox on your own domain)

The same steps work (`MAILBOX_n=outlook`), signed in with that mailbox. Its limits are far higher (thousands a
day), and with your own domain you control SPF, DKIM and DMARC (`wr dns yourdomain.com`), which is the best setup
for staying out of spam (docs/DELIVERABILITY.md).
