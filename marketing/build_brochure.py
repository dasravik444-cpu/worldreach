"""The overview PDF for businesses: two pages, US Letter (marketing/brochure.pdf).

    python marketing/build_brochure.py                  # -> marketing/brochure.pdf (details from brochure.json)
    python marketing/build_brochure.py --png            # also page images, to check the layout
    python marketing/build_brochure.py --phone "+91 ..." --email you@x.com --out marketing/own/brochure.pdf
                                                        # your own copy with your number (never uploaded)

Drawn as an HTML page and printed to PDF by Chromium (Playwright, through node), with the Inter font embedded
(marketing/fonts), so it can be rebuilt in seconds when the services or prices change.

What it promises has to stay deliverable: follow-up messages from the business's own customer list, by e-mail, to
people who agreed; review requests within Google's rules (everyone asked the same way, nothing in return).
No invented numbers, clients or guarantees.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
INK, MUTED, LINE = "#101828", "#5B6676", "#E4E7EC"
NAVY, VIOLET, LAVENDER, TEAL, GOLD, GREEN = "#25206F", "#4F46E5", "#EEF2FF", "#14B8A6", "#FFC93C", "#138A52"


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def fonts_css() -> str:
    out = []
    for f in sorted((HERE / "fonts").glob("inter-latin-*-normal.woff2")):
        weight = f.name.split("-")[2]
        data = base64.b64encode(f.read_bytes()).decode("ascii")
        out.append(f"@font-face {{ font-family: BInter; font-weight: {weight}; font-style: normal; "
                   f"src: url(data:font/woff2;base64,{data}) format('woff2'); }}")
    return "\n".join(out)


def logo(d: dict, size: int = 30, light: bool = False) -> str:
    icon = (HERE / "brand" / "aurenflow-icon.svg").read_text(encoding="utf-8")
    icon = icon.replace('width="1024" height="1024"', f'width="{size}" height="{size}"')
    brand, accent = str(d["brand"]), str(d.get("brand_accent") or "")
    head = brand[:-len(accent)] if accent and brand.endswith(accent) else brand
    tail = accent if accent and brand.endswith(accent) else ""
    color = "#fff" if light else NAVY
    return (f'<span class="logo">{icon}<span style="color:{color}">{esc(head)}'
            f'<span style="color:{"#A5F3E8" if light else VIOLET}">{esc(tail)}</span></span></span>')


ICONS = {
    "back": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "card": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
    "star": '<path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
}


def icon(name: str, size: int = 20, color: str = VIOLET) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


SERVICES = [
    ("back", "Win-back", "Customers who stopped coming",
     "A short, friendly series to the people who have not been in for months. Most of them did not leave; they "
     "drifted.",
     "Hi Maria, it's been a while since your last class at Lotus Yoga. We'd love to see you again - shall we save "
     "you a spot this week?"),
    ("bell", "Come-back reminders", "Customers who are due",
     "A note at the right moment: the next cut, the next service, the next season's stay.",
     "Hi James, it's been six weeks since your last cut at Maple Street. Want us to hold your usual Saturday slot?"),
    ("card", "Payment reminders", "Fees that slipped",
     "Polite, private reminders when a payment fails or a renewal is missed, before a member quietly lapses.",
     "Hi Alex, your November membership payment didn't go through. You can update your card at the front desk or "
     "just reply here."),
    ("star", "Google reviews", "Happy customers who never say so",
     "A thank-you after the visit with one tap to your Google review page. Everyone is asked the same way.",
     "Thanks for staying with us, Priya! If you have a minute, a Google review helps other travellers find us."),
]
STEPS = [
    ("You send us your list", "An export from your booking or membership system. We show you where the button is. "
                              "Your list stays yours and is used for nothing else."),
    ("We write, you approve", "Messages in your voice, with your name on them. Nothing goes out until you have "
                              "read and approved every word."),
    ("They go out; replies come to you", "At the right moment for each customer, a few a day, never a blast. "
                                         "Every answer lands in your inbox, and a report every month."),
]
WHO = ["Gyms and studios", "Martial arts schools", "Salons and spas", "Hotels and guesthouses",
       "Restaurants and cafes", "Groomers and pet care", "Garages and detailers"]
FAIR = [
    ("Only people who agreed", "Messages go to your own customers who gave you their details and can hear from "
                               "you. Every message says how to stop, and a stop is honoured at once."),
    ("Reviews within Google's rules", "Everyone is asked the same way, nothing is offered in return, and nobody "
                                      "is filtered out. That keeps your reviews, and your profile, safe."),
    ("Your data stays yours", "We use your list only for your messages, never share or sell it, and delete it "
                              "when you ask."),
]

CSS = """
@page { size: 8.5in 11in; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: BInter, Inter, Arial, sans-serif; color: %(INK)s; font-size: 10.4pt; line-height: 1.42; }
.page { width: 8.5in; height: 11in; padding: 0.42in 0.6in 0.36in; position: relative; overflow: hidden;
        page-break-after: always; display: flex; flex-direction: column; }
.logo { display: inline-flex; align-items: center; gap: 9px; font-weight: 800; font-size: 17pt; letter-spacing: -0.3px; }
.logo svg { border-radius: 8px; }
.top { display: flex; justify-content: space-between; align-items: center; }
.tag { color: %(MUTED)s; font-size: 9.6pt; font-weight: 600; }
h1 { font-size: 27pt; line-height: 1.12; letter-spacing: -0.8px; font-weight: 800; color: %(NAVY)s; margin-top: 0.26in; }
h1 em { font-style: normal; color: %(VIOLET)s; }
.lead { font-size: 11.6pt; color: #344054; margin-top: 12px; max-width: 6.3in; }
h2 { font-size: 13pt; font-weight: 800; color: %(NAVY)s; letter-spacing: -0.2px; margin: 0.2in 0 8px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.card { border: 1px solid %(LINE)s; border-radius: 12px; padding: 11px 13px 10px; background: #fff; }
.card .head { display: flex; align-items: center; gap: 9px; }
.card .ic { width: 34px; height: 34px; border-radius: 9px; background: %(LAVENDER)s; display: flex; align-items: center;
            justify-content: center; flex: none; }
.card b { font-size: 11.4pt; font-weight: 700; display: block; line-height: 1.2; }
.card .sub { color: %(MUTED)s; font-size: 8.8pt; font-weight: 600; }
.card p { font-size: 9.3pt; color: #344054; margin-top: 6px; }
.bubble { margin-top: 7px; background: #F2F4F7; border-radius: 4px 12px 12px 12px; padding: 8px 10px; font-size: 8.7pt;
          color: #1D2939; }
.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.step .n { width: 24px; height: 24px; border-radius: 12px; background: %(NAVY)s; color: #fff; font-weight: 700;
           font-size: 9.6pt; display: flex; align-items: center; justify-content: center; }
.step b { display: block; margin-top: 7px; font-size: 10.4pt; }
.step p { font-size: 9.1pt; color: #475467; margin-top: 3px; }
.who { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 2px; }
.who span { border: 1px solid #D0D5DD; border-radius: 999px; padding: 3px 11px; font-size: 8.9pt; font-weight: 600;
            color: #344054; }
.foot { margin-top: auto; display: flex; justify-content: space-between; color: %(MUTED)s; font-size: 8pt;
        border-top: 1px solid %(LINE)s; padding-top: 8px; }
.plans { display: grid; grid-template-columns: repeat(3, 1fr); gap: 11px; align-items: stretch; }
.plan { border: 1px solid %(LINE)s; border-radius: 13px; padding: 14px 14px 10px; position: relative; background: #fff; }
.plan.pop { border: 2px solid %(VIOLET)s; background: #FAFAFF; }
.plan .badge { position: absolute; top: -10px; left: 14px; background: %(VIOLET)s; color: #fff; font-size: 7.6pt;
               font-weight: 700; border-radius: 999px; padding: 2px 9px; letter-spacing: 0.3px; }
.plan .name { font-weight: 800; font-size: 12.4pt; color: %(NAVY)s; }
.plan .for { color: %(MUTED)s; font-size: 8.8pt; min-height: 2.5em; margin-top: 2px; }
.plan .price { font-size: 23pt; font-weight: 800; letter-spacing: -0.8px; margin-top: 6px; }
.plan .price small { font-size: 9pt; font-weight: 600; color: %(MUTED)s; letter-spacing: 0; }
.plan ul { list-style: none; margin-top: 9px; }
.plan li { display: flex; gap: 7px; font-size: 9pt; color: #344054; margin-top: 5px; align-items: flex-start; }
.plan li svg { flex: none; margin-top: 2px; }
.sprint { margin-top: 12px; border-radius: 13px; background: %(LAVENDER)s; padding: 12px 15px; display: flex;
          justify-content: space-between; align-items: center; gap: 18px; }
.sprint b { color: %(NAVY)s; font-size: 11.2pt; }
.sprint p { font-size: 9.2pt; color: #344054; margin-top: 2px; }
.sprint .price { font-size: 19pt; font-weight: 800; white-space: nowrap; color: %(NAVY)s; text-align: right; }
.sprint .price small { display: block; font-size: 8.6pt; font-weight: 600; color: %(MUTED)s; }
.terms { font-size: 9.2pt; color: #475467; margin-top: 9px; }
.fair { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.fair b { font-size: 10pt; display: block; }
.fair p { font-size: 9pt; color: #475467; margin-top: 3px; }
.cta { margin-top: 0.16in; border-radius: 15px; background: linear-gradient(120deg, %(NAVY)s 0%%, %(VIOLET)s 75%%, #7C3AED 100%%);
       color: #fff; padding: 14px 20px; display: flex; justify-content: space-between; align-items: center; gap: 20px; }
.cta h3 { font-size: 14.5pt; font-weight: 800; letter-spacing: -0.3px; }
.cta p { font-size: 9.8pt; opacity: 0.92; margin-top: 3px; }
.cta .contact { font-size: 10pt; line-height: 1.6; text-align: right; white-space: nowrap; font-weight: 600; }
.math { border-left: 3px solid %(TEAL)s; padding: 2px 0 2px 12px; margin-top: 4px; font-size: 9.8pt; color: #344054; }
""" % {"INK": INK, "MUTED": MUTED, "LINE": LINE, "NAVY": NAVY, "VIOLET": VIOLET, "LAVENDER": LAVENDER, "TEAL": TEAL}


def money(d: dict, amount) -> str:
    return f"{d.get('currency', '$')}{amount:,}" if isinstance(amount, (int, float)) else esc(amount)


def page_one(d: dict) -> str:
    cards = "".join(
        f'<div class="card"><div class="head"><div class="ic">{icon(i)}</div><div><b>{esc(t)}</b>'
        f'<span class="sub">{esc(s)}</span></div></div><p>{esc(p)}</p><div class="bubble">{esc(m)}</div></div>'
        for i, t, s, p, m in SERVICES)
    steps = "".join(f'<div class="step"><div class="n">{n}</div><b>{esc(t)}</b><p>{esc(p)}</p></div>'
                    for n, (t, p) in enumerate(STEPS, start=1))
    who = "".join(f"<span>{esc(w)}</span>" for w in WHO)
    return f"""<section class="page">
<div class="top">{logo(d)}<span class="tag">{esc(d.get("tagline"))}</span></div>
<h1>Your best new customers are the ones <em>you already had.</em></h1>
<p class="lead">Every local business has a list of people who came, liked it, and drifted away. Nobody has the time to
write to each of them. We do it for you: the right message to the right customer at the right moment, from the list
you already have.</p>
<h2>What we take off your desk</h2>
<div class="grid">{cards}</div>
<h2>How it works</h2>
<div class="steps">{steps}</div>
<h2>Made for</h2>
<div class="who">{who}</div>
<div class="foot"><span>{esc(d["brand"])} · {esc(d.get("tagline"))}</span><span>1 / 2</span></div>
</section>"""


def page_two(d: dict) -> str:
    plans = ""
    for p in d.get("plans") or []:
        items = "".join(f"<li>{icon('check', 13, GREEN)}<span>{esc(x)}</span></li>" for x in p.get("items") or [])
        plans += (f'<div class="plan{" pop" if p.get("popular") else ""}">'
                  + ('<span class="badge">RECOMMENDED</span>' if p.get("popular") else "")
                  + f'<div class="name">{esc(p["name"])}</div><div class="for">{esc(p.get("for"))}</div>'
                  + (f'<div class="price">{money(d, p["price"])} <small>/ {esc(p.get("per", "month"))}</small></div>'
                     if d.get("show_prices", True) else "")
                  + f"<ul>{items}</ul></div>")
    s = d.get("sprint") or {}
    sprint = ""
    if s:
        price = (f'<div class="price">{money(d, s["price"])}<small>{esc(s.get("per", "one time"))}</small></div>'
                 if d.get("show_prices", True) else "")
        sprint = f'<div class="sprint"><div><b>{esc(s["name"])}</b><p>{esc(s.get("text"))}</p></div>{price}</div>'
    fair = "".join(f"<div><b>{esc(t)}</b><p>{esc(p)}</p></div>" for t, p in FAIR)
    contact = [x for x in (d.get("name"), d.get("email"), (f"WhatsApp {d['phone']}" if d.get("phone") else ""),
                           d.get("website")) if x]
    return f"""<section class="page">
<div class="top">{logo(d)}<span class="tag">{esc(d.get("tagline"))}</span></div>
<h2 style="margin-top:0.24in">The sum is simple</h2>
<p class="math">Take a studio with 300 past members. If only 5 in 100 come back, that is 15 memberships from people who
already know the way to your door, without a cent spent on advertising. The same sum works for a salon's overdue
clients, a hotel's past guests and a garage's customers who are due. <b>These are sums, not promises:</b> what comes
back depends on your list and your offer, and your monthly report shows exactly who did.</p>
<h2>{"Plans" if d.get("show_prices", True) else "What you can choose"}</h2>
<div class="plans">{plans}</div>
{sprint}
<p class="terms"><b>{esc(d.get("terms"))}</b> {esc(d.get("channels"))}</p>
<h2>Fair to your customers, safe for you</h2>
<div class="fair">{fair}</div>
<div class="cta"><div><h3>Want to see it with your own customers?</h3>
<p>Reply to our e-mail with a day and time for a 15-minute call. We look at your list together and show you the first
messages we would send. No obligation, and nothing goes out without your yes.</p></div>
<div class="contact">{"<br>".join(esc(x) for x in contact)}</div></div>
<div class="foot"><span>{esc(d["brand"])} · edition {esc(d.get("edition"))}</span><span>2 / 2</span></div>
</section>"""


def build_html(d: dict) -> str:
    title = f"{d['brand']} overview, edition {d.get('edition', '')}"
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{esc(title)}</title>'
            f"<style>{fonts_css()}\n{CSS}</style></head><body>{page_one(d)}{page_two(d)}</body></html>")


NODE = """
const { chromium } = require('playwright');
(async () => {
  const [html, pdf, png] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 816, height: 1056 }, deviceScaleFactor: 2 });
  await page.goto('file://' + html);
  await page.pdf({ path: pdf, width: '8.5in', height: '11in', printBackground: true });
  if (png) {
    const pages = await page.$$('section.page');
    for (let i = 0; i < pages.length; i++) await pages[i].screenshot({ path: png.replace('%d', String(i + 1)) });
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(HERE / "brochure.pdf"))
    ap.add_argument("--png", action="store_true", help="also page images next to the PDF")
    ap.add_argument("--html", action="store_true", help="only write the HTML (no Chromium needed)")
    for key in ("name", "email", "phone", "website", "brand"):
        ap.add_argument(f"--{key}", default=None)
    ap.add_argument("--no-prices", action="store_true")
    a = ap.parse_args(argv)
    d = json.loads((HERE / "brochure.json").read_text(encoding="utf-8"))
    for key in ("name", "email", "phone", "website", "brand"):
        if getattr(a, key) is not None:
            d[key] = getattr(a, key)
    if a.no_prices:
        d["show_prices"] = False
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    page = build_html(d)
    if a.html:
        out.with_suffix(".html").write_text(page, encoding="utf-8")
        print(f"wrote {out.with_suffix('.html')}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "brochure.html"
        src.write_text(page, encoding="utf-8")
        js = Path(tmp) / "print.js"
        js.write_text(NODE, encoding="utf-8")
        png = str(out.with_name(out.stem + "-page%d.png")) if a.png else ""
        env = {**os.environ, "NODE_PATH": os.environ.get("NODE_PATH", "") or subprocess.run(
            ["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()}
        r = subprocess.run(["node", str(js), str(src), str(out), png], env=env)
        if r.returncode != 0:
            print("Could not print the PDF: this needs node with Playwright and Chromium (not on the tablet; the PDF "
                  "in the code is built for you).")
            return 1
    print(f"wrote {out} (edition {d.get('edition')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
