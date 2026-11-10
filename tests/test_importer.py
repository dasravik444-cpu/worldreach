"""Lead lists from GitHub runs (leads-<city>.zip / CSV) into the Google Sheet, with today's rules applied again."""
from __future__ import annotations

import csv
import zipfile

from conftest import make_config
from helpers import FakeSheetsSession

from leadgen.importer import import_leads, read_lead_files
from leadgen.sheets import KEY_COL, LEAD_COLUMNS, SheetsClient, SheetsSync


def lead(key, name, lead_id, *, emails="", whatsapp="", phones="", status="New"):
    r = {c: "" for c in LEAD_COLUMNS}
    r.update({"Key": key, "Business Name": name, "Lead ID": lead_id, "Emails": emails, "WhatsApp": whatsapp,
              "Phones": phones, "Status": status})
    return r


def test_lead_list_is_added_with_todays_rules_and_known_businesses_are_left_alone(tmp_path):
    cfg = make_config(filters={"exclude_chains": ["Domino"]}, sheets={"require_any": ["email", "whatsapp"]})
    sess = FakeSheetsSession()
    sync = SheetsSync(SheetsClient("sheet", session=sess), "Leads", "", "")
    sync.ensure_tabs()
    sync.upsert_leads([lead("ov:1", "Leaf Cafe", "AUS-00001", emails="hi@leafcafe.com", status="Emailed")])
    rows = [lead("ov:1", "Leaf Cafe", "AUS-00007", emails="other@leafcafe.com"),          # already in the sheet
            lead("ov:2", "Domino's Pizza", "AUS-00002", emails="store@dominos.com"),       # big chain
            lead("ov:3", "Wave Bakery", "AUS-00003", emails="templates@wavesdesign.io"),   # a theme's address only
            lead("ov:4", "Brew House", "AUS-00001", emails="hello@brewhouse.com\ntest@brewhouse.com"),
            lead("ov:5", "Tea Spot", "AUS-00005", whatsapp="+1 512 555 0100", phones="'-"),
            lead("ov:4", "Brew House", "AUS-00001", emails="hello@brewhouse.com")]          # listed twice
    path = tmp_path / "leads-austin.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEAD_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with zipfile.ZipFile(tmp_path / "leads-austin.zip", "w") as zf:      # what GitHub offers for download
        zf.write(path, "leads-austin.csv")

    stats = import_leads(sync, cfg, read_lead_files([str(tmp_path / "leads-austin.zip")]))
    sheet = {r[KEY_COL]: dict(zip(LEAD_COLUMNS, r)) for r in sess.tabs["Leads"]["rows"][1:]}
    assert set(sheet) == {"ov:1", "ov:4", "ov:5"}
    assert sheet["ov:1"]["Status"] == "Emailed" and sheet["ov:1"]["Emails"] == "hi@leafcafe.com"   # untouched
    assert sheet["ov:4"]["Lead ID"] == "AUS-00002" and sheet["ov:4"]["Emails"] == "hello@brewhouse.com"
    assert sheet["ov:5"]["Phones"] == "-" and sheet["ov:5"]["Status"] == "New"
    assert stats["added to the sheet"] == 2 and stats["already in the sheet"] == 1
    assert stats["left out: big chain"] == 1 and stats["left out: no usable e-mail or WhatsApp"] == 1
    assert stats["left out: no key, or listed twice"] == 1 and stats["given a new Lead ID (number taken)"] == 1

    again = import_leads(sync, cfg, read_lead_files([str(path)]))           # importing twice adds nothing
    assert again.get("added to the sheet", 0) == 0 and again["already in the sheet"] == 3
