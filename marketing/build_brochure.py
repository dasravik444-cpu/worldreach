"""The overview PDF for businesses: two pages, US Letter.

    python marketing/build_brochure.py                       # -> marketing/brochure.pdf (no phone or e-mail in it)
    python marketing/build_brochure.py --png                 # also page images, to check the layout
    python marketing/build_brochure.py --phone "+91 ..." --email you@x.com --out marketing/own/Aurenflow-overview.pdf
                                                             # your own copy with your contact details (never uploaded)

The look follows financial-services brochures: a serif headline face (Playfair Display) with a clean sans body
(Inter), deep navy with a muted gold accent, warm white, generous space, very little text. Every service is one
short line with a drawn illustration (inline SVG, made here: no stock images, nothing to license). No logo and no
prices (the owner's decision, 13 November 2026). The words live in marketing/brochure.json.

Printed to PDF by Chromium (Playwright, through node), with the fonts embedded (marketing/fonts).
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
INK, NAVY, NAVY2 = "#0E1A2B", "#13294B", "#1F3A63"
GOLD, GOLD_L, GOLD_XL = "#B08D57", "#E6D7BC", "#F4ECDD"
IVORY, PANEL = "#FBF9F4", "#F3EEE4"
SKY, SKY_D = "#D3DDEA", "#8EA6C6"
SKIN, HAIR = "#E7B48E", "#3B2A22"
GREY, LINE = "#566070", "#E4DDCF"


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def fonts_css() -> str:
    out = []
    for f in sorted((HERE / "fonts").glob("*.woff2")):
        family = "Serif" if f.name.startswith("playfair") else "Sans"
        parts = f.stem.split("-")
        weight, style = parts[-2], parts[-1]
        data = base64.b64encode(f.read_bytes()).decode("ascii")
        out.append(f"@font-face {{ font-family: B{family}; font-weight: {weight}; font-style: {style}; "
                   f"src: url(data:font/woff2;base64,{data}) format('woff2'); }}")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------- illustrations
def svg(body: str, w: int = 160, h: int = 120, bg: bool = True) -> str:
    back = (f'<ellipse cx="{w / 2}" cy="{h / 2 + 4}" rx="{w * 0.36}" ry="{h * 0.43}" fill="{PANEL}"/>'
            f'<ellipse cx="{w / 2}" cy="{h - 10}" rx="{w * 0.33}" ry="5" fill="{GOLD_L}" opacity=".55"/>' if bg else "")
    return (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" stroke-linecap="round" '
            f'stroke-linejoin="round">{back}{body}</svg>')


def star(cx: float, cy: float, r: float, fill: str = GOLD) -> str:
    import math

    pts = []
    for k in range(10):
        rad = r if k % 2 == 0 else r * 0.45
        a = -math.pi / 2 + k * math.pi / 5
        pts.append(f"{cx + rad * math.cos(a):.1f},{cy + rad * math.sin(a):.1f}")
    return f'<polygon points="{" ".join(pts)}" fill="{fill}"/>'


def heart(x: float, y: float, s: float, fill: str) -> str:
    return (f'<path transform="translate({x} {y}) scale({s})" d="M0 -3 C-2 -8 -10 -7 -10 -1 C-10 4 -3 8 0 11 '
            f'C3 8 10 4 10 -1 C10 -7 2 -8 0 -3z" fill="{fill}"/>')


def person(x: float, y: float, coat: str, s: float = 1.0, hair: str = HAIR, walk: bool = False) -> str:
    legs = ('<path d="M-5 24 L-9 40 M5 24 L10 40" stroke="{c}" stroke-width="5"/>' if walk else
            '<path d="M-4 24 L-4 40 M4 24 L4 40" stroke="{c}" stroke-width="5"/>').format(c=INK)
    return (f'<g transform="translate({x} {y}) scale({s})">{legs}'
            f'<path d="M-11 26 C-11 8 11 8 11 26 Z" fill="{coat}"/>'
            f'<rect x="-3" y="2" width="6" height="6" fill="{SKIN}"/>'
            f'<circle cx="0" cy="-4" r="8" fill="{SKIN}"/>'
            f'<path d="M-8 -5 C-8 -14 8 -14 8 -5 C5 -9 -3 -10 -8 -5z" fill="{hair}"/></g>')


ART = {
    "sales": lambda: svg(
        f'<rect x="28" y="54" width="66" height="48" fill="#fff" stroke="{NAVY}" stroke-width="2.4"/>'
        f'<rect x="24" y="40" width="74" height="15" rx="2" fill="{NAVY}"/>'
        + "".join(f'<path d="M{24 + i * 12.33} 55 a6.17 6.17 0 0 0 12.33 0z" fill="{NAVY if i % 2 else GOLD}"/>'
                  for i in range(6))
        + f'<rect x="51" y="70" width="20" height="32" fill="{SKY}" stroke="{NAVY}" stroke-width="2"/>'
          f'<circle cx="66" cy="87" r="1.6" fill="{NAVY}"/>'
          f'<rect x="34" y="66" width="12" height="12" fill="{SKY_D}"/><rect x="76" y="66" width="12" height="12" fill="{SKY_D}"/>'
          f'<rect x="104" y="80" width="9" height="22" rx="1.5" fill="{GOLD_L}"/>'
          f'<rect x="117" y="68" width="9" height="34" rx="1.5" fill="{GOLD_L}"/>'
          f'<rect x="130" y="54" width="9" height="48" rx="1.5" fill="{GOLD}"/>'
          f'<path d="M100 74 L118 58 L126 63 L142 40" fill="none" stroke="{NAVY}" stroke-width="3"/>'
          f'<path d="M134 39 L143 38 L142 47" fill="none" stroke="{NAVY}" stroke-width="3"/>'),
    "reviews": lambda: svg(
        f'<rect x="46" y="16" width="56" height="92" rx="10" fill="{NAVY}"/>'
        f'<rect x="51" y="25" width="46" height="74" rx="4" fill="#fff"/>'
        f'<circle cx="62" cy="37" r="6" fill="{SKY}"/><rect x="71" y="33" width="20" height="3.5" rx="1.7" fill="{SKY_D}"/>'
        f'<rect x="71" y="39" width="13" height="3" rx="1.5" fill="{SKY}"/>'
        + "".join(star(57 + i * 8.6, 55, 3.9) for i in range(5))
        + f'<rect x="56" y="65" width="36" height="3" rx="1.5" fill="{SKY}"/>'
          f'<rect x="56" y="72" width="30" height="3" rx="1.5" fill="{SKY}"/>'
          f'<rect x="56" y="79" width="33" height="3" rx="1.5" fill="{SKY}"/>'
          f'<rect x="96" y="22" width="44" height="30" rx="11" fill="{GOLD}"/>'
          f'<path d="M106 50 L102 60 L114 51z" fill="{GOLD}"/>' + heart(118, 35, 0.95, "#fff")
        + star(30, 86, 11, GOLD) + star(132, 84, 7, GOLD_L)),
    "followup": lambda: svg(
        f'<rect x="32" y="50" width="80" height="52" rx="5" fill="#fff" stroke="{NAVY}" stroke-width="2.4"/>'
        f'<path d="M32 52 L72 80 L112 52" fill="none" stroke="{NAVY}" stroke-width="2.4"/>'
        f'<path d="M32 100 L62 74 M112 100 L82 74" stroke="{SKY_D}" stroke-width="2"/>'
        f'<circle cx="112" cy="52" r="10" fill="{GOLD}"/>'
        f'<text x="112" y="56.5" text-anchor="middle" font-family="BSans" font-weight="700" font-size="12" fill="#fff">1</text>'
        f'<path d="M58 40 C70 22 98 20 112 30" fill="none" stroke="{GOLD}" stroke-width="2" stroke-dasharray="3 5"/>'
        f'<path d="M116 16 L144 10 L130 34 L124 25z" fill="{NAVY}"/><path d="M124 25 L144 10 L120 30z" fill="{NAVY2}"/>'),
    "reminder": lambda: svg(
        f'<rect x="30" y="30" width="72" height="72" rx="7" fill="#fff" stroke="{NAVY}" stroke-width="2.4"/>'
        f'<path d="M30 48 V37 a7 7 0 0 1 7 -7 H95 a7 7 0 0 1 7 7 V48z" fill="{NAVY}"/>'
        f'<rect x="44" y="23" width="5" height="13" rx="2.5" fill="{GOLD}"/><rect x="83" y="23" width="5" height="13" rx="2.5" fill="{GOLD}"/>'
        + "".join(f'<rect x="{39 + c * 14}" y="{56 + r * 13}" width="8" height="7" rx="1.5" fill="{SKY}"/>'
                  for r in range(3) for c in range(4) if (r, c) != (1, 2))
        + f'<circle cx="71" cy="72.5" r="8.5" fill="{GOLD}"/>'
          f'<path d="M67 72.5 l3 3 l5.5 -6" fill="none" stroke="#fff" stroke-width="2.2"/>'
          f'<path d="M118 52 c-9 0 -12 8 -12 16 v8 l-5 6 h34 l-5 -6 v-8 c0 -8 -3 -16 -12 -16z" fill="{GOLD}"/>'
          f'<circle cx="118" cy="86" r="4.5" fill="{GOLD}"/><circle cx="118" cy="49" r="3" fill="{GOLD}"/>'
          f'<path d="M140 56 q6 10 0 20 M96 56 q-6 10 0 20" fill="none" stroke="{GOLD_L}" stroke-width="2.4"/>'),
    "winback": lambda: svg(
        f'<rect x="84" y="28" width="44" height="76" rx="2" fill="{NAVY}"/>'
        f'<rect x="89" y="33" width="34" height="71" fill="{GOLD_XL}"/>'
        f'<path d="M89 33 L111 40 L111 108 L89 104z" fill="#fff" stroke="{NAVY}" stroke-width="2"/>'
        f'<circle cx="106" cy="72" r="1.8" fill="{NAVY}"/>'
        f'<rect x="80" y="104" width="52" height="5" rx="2" fill="{GOLD}"/>'
        + person(54, 58, SKY_D, 1.05, walk=True)
        + f'<path d="M62 72 Q70 70 76 64" fill="none" stroke="{SKY_D}" stroke-width="5"/><circle cx="77" cy="63" r="3" fill="{SKIN}"/>'
        + heart(106, 14, 1.0, GOLD) + heart(72, 30, 0.6, GOLD_L)),
    "payment": lambda: svg(
        f'<rect x="28" y="44" width="84" height="56" rx="8" fill="{NAVY}"/>'
        f'<rect x="28" y="56" width="84" height="10" fill="{INK}"/>'
        f'<rect x="38" y="74" width="15" height="11" rx="2" fill="{GOLD}"/>'
        f'<rect x="60" y="78" width="40" height="3.5" rx="1.7" fill="{SKY_D}"/>'
        f'<rect x="60" y="86" width="26" height="3.5" rx="1.7" fill="{SKY_D}"/>'
        f'<circle cx="114" cy="46" r="17" fill="{GOLD}"/>'
        f'<path d="M106 46 l6 6 l11 -12" fill="none" stroke="#fff" stroke-width="3.6"/>'
        f'<circle cx="40" cy="30" r="7" fill="{GOLD_L}"/><circle cx="52" cy="24" r="5" fill="{GOLD_L}"/>'),
    "website": lambda: svg(
        f'<rect x="20" y="20" width="120" height="84" rx="8" fill="#fff" stroke="{NAVY}" stroke-width="2.4"/>'
        f'<path d="M20 36 V28 a8 8 0 0 1 8 -8 H132 a8 8 0 0 1 8 8 V36z" fill="{NAVY}"/>'
        f'<circle cx="30" cy="28" r="2.6" fill="{GOLD}"/><circle cx="38" cy="28" r="2.6" fill="{GOLD_L}"/>'
        f'<circle cx="46" cy="28" r="2.6" fill="{SKY_D}"/>'
        f'<rect x="30" y="44" width="56" height="32" rx="4" fill="{SKY}"/>'
        f'<path d="M34 72 L50 56 L60 66 L68 59 L82 72z" fill="{SKY_D}"/><circle cx="74" cy="52" r="4" fill="{GOLD}"/>'
        f'<rect x="94" y="46" width="36" height="5" rx="2.5" fill="{NAVY}"/>'
        f'<rect x="94" y="56" width="30" height="3.5" rx="1.7" fill="{SKY}"/>'
        f'<rect x="94" y="63" width="34" height="3.5" rx="1.7" fill="{SKY}"/>'
        f'<rect x="94" y="72" width="26" height="9" rx="4.5" fill="{GOLD}"/>'
        f'<rect x="30" y="84" width="100" height="3.5" rx="1.7" fill="{SKY}"/>'
        f'<rect x="30" y="91" width="70" height="3.5" rx="1.7" fill="{SKY}"/>'),
    "talk": lambda: svg(
        person(62, 66, NAVY, 1.0) + person(114, 66, GOLD, 1.0, hair="#6B4A32")
        + f'<rect x="36" y="16" width="50" height="30" rx="10" fill="#fff" stroke="{NAVY}" stroke-width="2"/>'
          f'<path d="M54 45 L56 54 L64 45z" fill="#fff" stroke="{NAVY}" stroke-width="2"/>'
          f'<path d="M54 44.5 H65" stroke="#fff" stroke-width="3"/>'
          f'<circle cx="49" cy="31" r="3" fill="{SKY_D}"/><circle cx="61" cy="31" r="3" fill="{SKY_D}"/>'
          f'<circle cx="73" cy="31" r="3" fill="{SKY_D}"/>'
          f'<rect x="96" y="20" width="40" height="26" rx="9" fill="{GOLD_L}"/><path d="M116 45 L112 53 L123 45z" fill="{GOLD_L}"/>'
          f'<text x="116" y="39" text-anchor="middle" font-family="BSerif" font-weight="700" font-size="17" fill="{NAVY}">?</text>'),
    "dig": lambda: svg(
        f'<rect x="26" y="24" width="78" height="74" rx="6" fill="#fff" stroke="{NAVY}" stroke-width="2.4"/>'
        f'<rect x="36" y="70" width="10" height="18" rx="1.5" fill="{SKY}"/><rect x="51" y="58" width="10" height="30" rx="1.5" fill="{SKY_D}"/>'
        f'<rect x="66" y="46" width="10" height="42" rx="1.5" fill="{GOLD_L}"/><rect x="81" y="36" width="10" height="52" rx="1.5" fill="{GOLD}"/>'
        f'<circle cx="104" cy="58" r="20" fill="#ffffff" fill-opacity=".55" stroke="{NAVY}" stroke-width="5"/>'
        f'<path d="M118 72 L136 92" stroke="{NAVY}" stroke-width="8"/>'
        f'<path d="M96 58 l6 6 l10 -12" fill="none" stroke="{GOLD}" stroke-width="3"/>'),
    "list": lambda: svg(
        f'<rect x="36" y="26" width="88" height="58" rx="5" fill="{NAVY}"/>'
        f'<rect x="41" y="31" width="78" height="48" rx="2" fill="#fff"/>'
        + "".join(f'<circle cx="50" cy="{40 + i * 11}" r="3.6" fill="{GOLD if i == 1 else SKY}"/>'
                  f'<rect x="58" y="{38 + i * 11}" width="{50 - (i % 2) * 14}" height="4" rx="2" fill="{SKY_D if i == 1 else SKY}"/>'
                  for i in range(4))
        + f'<path d="M26 92 L36 84 H124 L134 92z" fill="{SKY_D}"/><rect x="26" y="92" width="108" height="5" rx="2" fill="{NAVY}"/>'),
    "approve": lambda: svg(
        f'<rect x="42" y="18" width="62" height="86" rx="5" fill="#fff" stroke="{NAVY}" stroke-width="2.4"/>'
        + "".join(f'<rect x="52" y="{32 + i * 9}" width="{42 - (i % 3) * 8}" height="3.5" rx="1.7" fill="{SKY}"/>'
                  for i in range(6))
        + f'<path d="M52 92 q6 -8 12 0 t12 0" fill="none" stroke="{NAVY}" stroke-width="2"/>'
          f'<circle cx="106" cy="88" r="15" fill="{GOLD}"/>'
          f'<path d="M99 88 l5 5 l10 -11" fill="none" stroke="#fff" stroke-width="3.4"/>'
          f'<path d="M122 26 L92 70 L88 80 L96 74 L126 30z" fill="{NAVY2}"/><path d="M122 26 l4 4" stroke="{GOLD}" stroke-width="4"/>'),
    "growth": lambda: svg(
        person(52, 62, NAVY, 0.95) + person(80, 56, GOLD, 1.05, hair="#6B4A32") + person(108, 62, SKY_D, 0.95)
        + f'<path d="M36 34 L64 22 L84 28 L120 10" fill="none" stroke="{GOLD}" stroke-width="3"/>'
          f'<path d="M111 9 L121 9 L119 19" fill="none" stroke="{GOLD}" stroke-width="3"/>'),
}

ICONS = {
    "gym": '<path d="M5 12h14M3 9v6M21 9v6M6 7v10M18 7v10"/>',
    "yoga": '<circle cx="12" cy="4" r="2"/><path d="M12 7v7M12 9l-6-3M12 9l6-3M4 18c3-3 5-4 8-4s5 1 8 4M6 20h12"/>',
    "karate": '<path d="M2 10.5h7M15 10.5h7M2 13.5h7M15 13.5h7M10.5 14l-3 6M13.5 14l3 6"/><rect x="9" y="9" width="6" height="6" rx="1.2"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.1 8.1 20 20M8.1 15.9 20 4"/>',
    "bed": '<path d="M3 18V7M3 13h18v5M21 13a3 3 0 0 0-3-3h-8v3"/><circle cx="7" cy="10.5" r="1.8"/>',
    "cup": '<path d="M4 9h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM17 10h1.5a2.5 2.5 0 0 1 0 5H17M8 3c0 2 2 2 2 4M12 3c0 2 2 2 2 4"/>',
    "paw": '<circle cx="7" cy="9" r="1.8"/><circle cx="11" cy="6" r="1.8"/><circle cx="15" cy="7" r="1.8"/>'
           '<circle cx="18" cy="11" r="1.8"/><path d="M8 17c0-3 2-6 5-6s4 3 4 5-1.5 3-4 2.5S8 20 8 17z"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3l7.7-7.7a4 4 0 0 0-2-2zM14.7 6.3 17 4"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "phone": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 '
             '2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 '
             '0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
    "mail": '<rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="M3 6.5l9 6.5 9-6.5"/>',
}


def icon(name: str, size: int = 22, color: str = GOLD, width: float = 1.7) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


# ------------------------------------------------------------------------------------------- the pages
CSS = f"""
@page {{ size: 8.5in 11in; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: BSans, Arial, sans-serif; color: {INK}; font-size: 10.5pt; line-height: 1.45; background: #fff; }}
.page {{ width: 8.5in; height: 11in; padding: 0.55in 0.65in 0.45in; position: relative; overflow: hidden;
         page-break-after: always; display: flex; flex-direction: column; background: #fff; }}
.top {{ display: flex; justify-content: space-between; align-items: baseline; padding-bottom: 10px;
        border-bottom: 1px solid {GOLD}; }}
.mark {{ font-family: BSerif; font-weight: 600; font-size: 13pt; letter-spacing: 3.5px; color: {NAVY}; }}
.tag {{ font-size: 7.8pt; letter-spacing: 2.2px; text-transform: uppercase; color: {GREY}; font-weight: 600; }}
h1 {{ font-family: BSerif; font-weight: 500; font-size: 39pt; line-height: 1.07; letter-spacing: -0.6px;
      color: {INK}; margin-top: 0.34in; max-width: 6.9in; }}
h1 em {{ font-style: italic; font-weight: 400; color: {GOLD}; }}
.sub {{ font-size: 12.2pt; color: {GREY}; margin-top: 14px; max-width: 6.4in; line-height: 1.5; }}
.label {{ display: flex; align-items: center; gap: 12px; margin: 0.34in 0 14px; font-size: 8pt; letter-spacing: 2.6px;
          text-transform: uppercase; color: {GOLD}; font-weight: 700; }}
.label::after {{ content: ""; flex: 1; height: 1px; background: {LINE}; }}
.grid {{ display: grid; grid-template-columns: repeat(3, 1fr); column-gap: 22px; row-gap: 18px; }}
.tile .art {{ background: {IVORY}; border-radius: 16px; height: 1.14in; display: flex; align-items: center;
              justify-content: center; }}
.tile .art svg {{ height: 1.05in; width: auto; }}
.tile b {{ display: block; font-family: BSerif; font-weight: 600; font-size: 14.2pt; line-height: 1.2; color: {NAVY};
           margin-top: 11px; }}
.tile p {{ color: {GREY}; font-size: 10pt; margin-top: 4px; line-height: 1.4; }}
.tile.wide {{ grid-column: 1 / -1; display: grid; grid-template-columns: 2.2in 1fr; gap: 22px; align-items: center;
              background: {NAVY}; border-radius: 16px; padding: 10px 26px 10px 10px; }}
.tile.wide .art {{ height: 1.05in; background: {IVORY}; }}
.tile.wide .art svg {{ height: 0.98in; }}
.tile.wide b {{ color: #fff; margin-top: 0; font-size: 15.5pt; }}
.tile.wide p {{ color: #C9D3E2; font-size: 10.4pt; }}
.strip {{ margin-top: auto; display: flex; justify-content: space-between; align-items: center; gap: 16px;
          border-top: 1px solid {LINE}; padding-top: 13px; }}
.strip .ask {{ font-family: BSerif; font-size: 13.5pt; color: {NAVY}; font-weight: 500; }}
.contact {{ display: flex; gap: 22px; align-items: center; font-weight: 600; font-size: 10.4pt; color: {INK}; }}
.contact span {{ display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }}
.steps {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }}
.step .art {{ background: {IVORY}; border-radius: 16px; height: 1.6in; display: flex; align-items: center;
              justify-content: center; position: relative; }}
.step .art svg {{ height: 1.32in; max-width: 100%; width: auto; margin-top: 10px; }}
.step .n {{ position: absolute; top: 7px; left: 11px; font-family: BSerif; font-style: italic; font-size: 15pt; color: {GOLD}; }}
.step b {{ display: block; font-family: BSerif; font-weight: 600; font-size: 12.6pt; color: {NAVY}; margin-top: 11px; }}
.step p {{ color: {GREY}; font-size: 9.6pt; margin-top: 3px; }}
.inds {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
.ind {{ display: flex; align-items: center; gap: 10px; border: 1px solid {LINE}; border-radius: 12px; padding: 14px 12px;
        font-size: 9.8pt; font-weight: 600; color: {NAVY}; }}
.ind .i {{ width: 34px; height: 34px; border-radius: 50%; background: {GOLD_XL}; display: flex; align-items: center;
           justify-content: center; flex: none; }}
.promise {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin-bottom: 0.35in; }}
.promise div {{ display: flex; gap: 10px; align-items: flex-start; font-size: 10.6pt; color: {INK}; font-weight: 600;
                line-height: 1.35; }}
.promise svg {{ flex: none; margin-top: 1px; }}
.cta {{ margin-top: auto; margin-bottom: 4px; background: {NAVY}; border-radius: 18px; color: #fff; padding: 28px 30px;
        display: flex; justify-content: space-between; align-items: center; gap: 26px; }}
.cta h2 {{ font-family: BSerif; font-weight: 500; font-size: 25pt; line-height: 1.1; }}
.cta p {{ font-size: 10.6pt; color: #C9D3E2; margin-top: 8px; max-width: 3.7in; }}
.cta .contact {{ flex-direction: column; align-items: flex-start; gap: 10px; color: #fff; font-size: 11.6pt; }}
.foot {{ display: flex; justify-content: space-between; color: #8A92A0; font-size: 7.8pt; letter-spacing: 1px;
         margin-top: 14px; text-transform: uppercase; }}
"""


def contact_html(d: dict, light: bool = False) -> str:
    color = "#fff" if light else GOLD
    items = []
    if d.get("phone"):
        items.append(f'<span>{icon("phone", 17, color)}{esc(d["phone"])}</span>')
    if d.get("email"):
        items.append(f'<span>{icon("mail", 17, color)}{esc(d["email"])}</span>')
    if not items:
        items.append(f'<span>{icon("mail", 17, color)}{esc(d.get("contact_fallback"))}</span>')
    return f'<div class="contact">{"".join(items)}</div>'


def headline(text: str) -> str:
    """The last few words of the headline in gold italics ("... the customers <em>you already have.</em>")."""
    words = esc(text).split(" ")
    cut = max(1, len(words) - 3)
    return " ".join(words[:cut]) + " <em>" + " ".join(words[cut:]) + "</em>"


def top(d: dict) -> str:
    return f'<div class="top"><span class="mark">{esc(d["brand"]).upper()}</span><span class="tag">{esc(d["tagline"])}</span></div>'


def page_one(d: dict) -> str:
    tiles = "".join(
        (f'<div class="tile wide"><div class="art">{ART[s["art"]]()}</div><div><b>{esc(s["title"])}</b>'
         f'<p>{esc(s["text"])}</p></div></div>') if s.get("wide") else
        (f'<div class="tile"><div class="art">{ART[s["art"]]()}</div><b>{esc(s["title"])}</b>'
         f'<p>{esc(s["text"])}</p></div>') for s in d["services"])
    return f"""<section class="page">{top(d)}
<h1>{headline(d["headline"])}</h1>
<p class="sub">{esc(d["subline"])}</p>
<div class="label">What we do for you</div>
<div class="grid">{tiles}</div>
<div class="strip"><span class="ask">Talk to us</span>{contact_html(d)}</div>
<div class="foot"><span>{esc(d["brand"])}</span><span>1 / 2</span></div>
</section>"""


def page_two(d: dict) -> str:
    steps = "".join(f'<div class="step"><div class="art"><span class="n">0{i}</span>{ART[s["art"]]()}</div>'
                    f'<b>{esc(s["title"])}</b><p>{esc(s["text"])}</p></div>' for i, s in enumerate(d["steps"], start=1))
    inds = "".join(f'<div class="ind"><span class="i">{icon(x["icon"], 19, NAVY, 1.6)}</span>{esc(x["label"])}</div>'
                   for x in d["industries"])
    promise = "".join(f'<div>{icon("check", 20, GOLD, 2.4)}<span>{esc(p)}</span></div>' for p in d["promises"])
    return f"""<section class="page">{top(d)}
<div class="label" style="margin-top:0.4in">How it works</div>
<div class="steps">{steps}</div>
<div class="label">Made for</div>
<div class="inds">{inds}</div>
<div class="label">Our promise</div>
<div class="promise">{promise}</div>
<div class="cta"><div><h2>{esc(d["cta_title"])}</h2><p>{esc(d["cta_text"])}</p></div>{contact_html(d, light=True)}</div>
<div class="foot"><span>{esc(d["brand"])} · {esc(d["tagline"])}</span><span>2 / 2</span></div>
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
  await page.evaluate(() => document.fonts.ready);
  const over = await page.evaluate(() => [...document.querySelectorAll('section.page')]
    .map((s, i) => [i + 1, s.scrollHeight > s.clientHeight + 1]).filter(x => x[1]).map(x => x[0]));
  if (over.length) { console.error('content runs off page ' + over.join(', ')); process.exit(3); }
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
    ap.add_argument("--phone", default="")
    ap.add_argument("--email", default="")
    a = ap.parse_args(argv)
    d = json.loads((HERE / "brochure.json").read_text(encoding="utf-8"))
    d["phone"], d["email"] = a.phone.strip(), a.email.strip()
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
            print("Could not print the PDF (needs node with Playwright and Chromium; on the tablet use the PDF that "
                  "comes with the code)." if r.returncode != 3 else "The text is too long for the page: shorten it.")
            return 1
    print(f"wrote {out} (edition {d.get('edition')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
