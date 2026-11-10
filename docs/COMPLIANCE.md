# The rules, per country

A working summary with sources, written 10 November 2026. **Not legal advice.** The US, UK and Ireland parts rest
on the research done for the India robot's US/UK expansion (regulators' own pages); the rest of Europe rests on
secondary sources that partly contradict each other, and is marked so. Before a large campaign in a new country,
have a local lawyer check one e-mail.

## 1. Where a business may be e-mailed without having asked

| Country | First e-mail to a business | What every e-mail needs | In WorldReach |
|---|---|---|---|
| **United States** | Allowed (CAN-SPAM is an opt-out law, also for businesses) | Truthful sender and subject, **your postal address**, a way to say no that is honoured within 10 business days | on (`us`) |
| **United Kingdom** | Only **limited companies** (Ltd, LLP, PLC). Sole traders and partnerships need consent (PECR reg. 22) | Who writes, a way to say no; where the address came from (UK GDPR Art. 14) | on (`gb`): only leads whose website shows a company form are e-mailed |
| **Ireland** | Only **companies** (Ltd, DAC, PLC), about their business; sole traders need consent | as the UK | on (`ie`), same rule |
| Canada | Only an address the business **publishes itself**, about its business (CASL implied consent) | Your name, postal address, unsubscribe | rules ready, no city files yet |
| Australia, New Zealand | Only a conspicuously **published** business address, relevant message | Who writes, unsubscribe | rules ready; Australia has an open question on collecting addresses by software - ask first |
| **France** | Allowed to professional addresses when the offer concerns the person's job; opt-out (CNIL) | Who writes, where the address came from, a free and simple way to object | not built: needs French e-mails |
| **Sweden**, Finland | Reported allowed to legal persons (companies), not to sole traders | Who writes, opt-out | not built: needs company-form detection (AB, Oy) |
| Belgium, Portugal | Reported allowed to companies' impersonal addresses (info@) | Who writes, opt-out | not built |
| **Netherlands** | Consent, unless the business published the address for the purpose of being offered things; the regulator reads this narrowly, and sole traders count as persons | | treat as consent only |
| **Germany**, Austria, Switzerland | **Not allowed** without prior consent, businesses included (Germany: UWG § 7; competitors send paid warning letters) | | never e-mailed |
| **Spain, Italy, Poland, Denmark** | Consent required, businesses included | | never e-mailed |

So "Europe" starts with the **UK and Ireland**: English, clear rules, and built. France and Sweden are the next
candidates. Most of the rest of the EU cannot be cold e-mailed lawfully; there the way in is being found
(a website, a listing) or a first contact by letter.

`leadgen/country.py` holds each country's rule; the engine applies it to every lead by its own country
(`worldreach/outreach/engine.py`, `_pick`), and the summary of each run says how many leads were left out by rule.

## 2. What the code enforces

| Rule | Where |
|---|---|
| Postal address in every US e-mail (sending refuses to start without POSTAL_ADDRESS) | `Engine._sender_problem`, footer in `templates.py` |
| UK / Ireland: e-mail only companies | `Engine._pick` with the lead's Legal Form |
| Where the address came from + "reply delete" (UK, Ireland) | footer in `templates.py` |
| A business whose website says "no unsolicited offers" is skipped | lead finder (`no_marketing_notice`), `Engine._pick` |
| "No" / "stop" / "unsubscribe" / a bounce ends all contact, from every mailbox | `Engine._inbox_event`, the Do Not Contact tab |
| Only addresses the business published; nothing guessed | lead finder; `include_unverified = false` |
| Truthful subject and sender; no disguise | `templates.py`; mail goes out under your own name from your own mailbox |
| WhatsApp never automated | `android/whatsapp.sh` (you press Send) |

## 3. The service we sell: writing to a client's customers

- **The client's customers must have agreed** to hear from the client (a tick box at booking, a sign-up sheet).
  `customers.csv` has a consent column; without a "yes" a customer gets no marketing follow-up. A reminder about
  the customer's own missed payment is not marketing and goes without that column.
- **Every message says how to stop**, and a stop is final (`wr client stop`, or the customer replies STOP).
- **Reviews (Google's rules, the FTC's rule on reviews, the UK's DMCC Act):** everyone is asked the same way;
  nothing is offered in return; unhappy customers are not filtered out first. A review text that offers something
  or asks for five stars is refused by the tool.
- **The client's data:** the list is the client's. We use it only for the client's messages, keep it on the
  tablet (never in git, never in the Sheet), and delete it when asked. For a UK or Irish client we are their
  "processor" under GDPR and need a short data-processing agreement with them before the first message: have one
  drafted once and reuse it.
- **Text messages (SMS) in the US** need the customer's written consent and a registered sender (A2P 10DLC) through
  a provider such as Twilio; fines are per message (TCPA). Do not promise SMS to a US client before that is set up.
- **Health care** (dentists, clinics, chiropractors) is left out of the lead search on purpose: handling patient
  lists in the US needs a signed HIPAA agreement and matching safeguards.

## 4. Sources

- US: [FTC, CAN-SPAM Act: a compliance guide for business](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business); [FTC rule on consumer reviews, 16 CFR 465](https://www.ftc.gov/business-guidance/resources/soliciting-paying-online-reviews-guide-marketers)
- UK: [ICO, business-to-business marketing](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/); [CMA guidance on fake reviews, CMA208](https://gov.uk/government/publications/fake-reviews-cma208)
- Germany: [UWG § 7](https://www.gesetze-im-internet.de/uwg_2004/__7.html)
- Google: [Maps user-contributed content policy](https://support.google.com/contributionpolicy/answer/7400114)
- Rest of Europe (secondary, partly contradictory; verify before use): [ediware, B2B cold e-mailing legal framework](https://www.ediware.eu/b2b-email-marketing/b2b-cold-emailing-legal-framework/); [dotsland, B2B cold email rules by country](https://dotsland.com/en/b2b-cold-email-europe-by-country/); [Dealfront, cold calling and e-mailing laws in Europe](https://www.dealfront.com/guides/guide-to-cold-calling-and-emailing-europe); [overloop (Netherlands)](https://overloop.com/nl/blog/koude-acquisitie-wetgeving); [lawline.se (Sweden)](https://lawline.se/answers/kravs-samtycke-for-att-skicka-e-post-i-marknadsforingssyfte-till-person-pa-annat-foretag)
- Microsoft's sign-in change for Outlook: [Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/5837174/smtp-information-for-outlook); Exchange Online SMTP AUTH timeline: [Message Center MC786329](https://mc.merill.net/message/MC786329)
