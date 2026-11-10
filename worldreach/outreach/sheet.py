"""The outreach tabs of the Google Sheet (the lead tabs belong to the lead finder; only their Status cells are
written here).

  Outreach        one row per conversation: mailbox, stage, e-mails sent, next follow-up, the reply
  Email Preview   dry-run only: the exact e-mails that would go out now
  Replies         every reply with the next step (call, WhatsApp, removed)
  WhatsApp Queue  messages to send with one tap; the owner fills Result
  Do Not Contact  opt-outs and bounces; the owner can add e-mails, numbers or @domains
  Dashboard       everything at a glance, rewritten every run: mailboxes, businesses, replies, what to do now
  Outreach Report one line per run
"""
from __future__ import annotations

from leadgen.sheets import SheetsError, _cell, _tab_ref, col_letter

from .whatsapp import RESULTS

TABS = {
    "outreach": ["Lead ID", "Business", "Category", "City", "Country", "Email", "Mailbox", "Stage", "Emails Sent",
                 "Last Sent", "Next Follow-up", "Reply", "Phone", "Key"],
    "preview": ["Planned", "Lead ID", "Business", "To", "From", "Subject", "Body", "Text Check", "Key"],
    "replies": ["Received", "Lead ID", "Business", "Email", "Phone", "Reply Type", "Reply", "Next Step", "WhatsApp Chat",
                "To Mailbox", "Key"],
    "whatsapp": ["Date", "Lead ID", "Business", "Category", "Area", "Number", "Why", "Message", "Open Chat", "Result",
                 "Key"],
    "dnc": ["Email or Phone", "Reason", "Added", "Source"],
    "dashboard": ["What", "Now", "Details"],
    "report": ["Date", "Time", "Mode", "Mailboxes", "Limit Today", "Sent Today", "New E-mails", "Follow-ups",
               "Interested", "Not Interested", "Other Replies", "Bounces", "Skipped Addresses", "WhatsApp Queued",
               "Notes"],
}
WA_RESULT_COL = TABS["whatsapp"].index("Result")
WA_ROWS = 5000


class OutreachSheet:
    def __init__(self, client, names: dict):
        self.c = client
        self.names = names            # logical tab -> title in the Sheet

    def ref(self, tab: str) -> str:
        return _tab_ref(self.names[tab])

    def ensure_tabs(self) -> None:
        tabs = self.c.tabs()
        missing = [t for t in TABS if self.names[t] not in tabs]
        if missing:
            self.c.batch_update([{"addSheet": {"properties": {
                "title": self.names[t], "gridProperties": {"rowCount": WA_ROWS if t == "whatsapp" else 1000,
                                                           "columnCount": len(TABS[t]) + 2, "frozenRowCount": 1}}}}
                for t in missing])
            tabs = self.c.tabs()
        for t, cols in TABS.items():
            head = self.c.get_values(f"{self.ref(t)}!A1:{col_letter(len(cols) - 1)}1")
            current = [x.strip() for x in (head[0] if head else [])]
            if not any(current):
                sid = tabs[self.names[t]]["sheetId"]
                self.c.update_values(f"{self.ref(t)}!A1", [cols])
                reqs = [{"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                                                       "backgroundColor": {"red": 0.85, "green": 0.9,
                                                                                           "blue": 0.98}}},
                                        "fields": "userEnteredFormat(textFormat,backgroundColor)"}}]
                if t == "whatsapp":
                    reqs.append({"setDataValidation": {
                        "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": WA_ROWS,
                                  "startColumnIndex": WA_RESULT_COL, "endColumnIndex": WA_RESULT_COL + 1},
                        "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in RESULTS]},
                                 "showCustomUi": True, "strict": False}}})
                self.c.batch_update(reqs)
            elif current[:len(cols)] != cols:
                raise SheetsError(f"tab '{self.names[t]}' has other headers ({current[:4]}...) - rename that tab; "
                                  "outreach will not overwrite it")

    # -- the owner's input ---------------------------------------------------------
    def read_dnc(self) -> list[tuple[str, str]]:
        rows = self.c.get_values(f"{self.ref('dnc')}!A2:B")
        return [(str(r[0]).strip(), str(r[1]).strip() if len(r) > 1 else "") for r in rows if r and str(r[0]).strip()]

    def read_whatsapp_results(self) -> list[tuple[str, str, str]]:
        """[(key, number, result cell)] for every queue row."""
        n_col, r_col, k_col = (col_letter(TABS["whatsapp"].index(c)) for c in ("Number", "Result", "Key"))
        ref = self.ref("whatsapp")
        nums, results, keys = self.c.batch_get_columns([f"{ref}!{n_col}2:{n_col}", f"{ref}!{r_col}2:{r_col}",
                                                        f"{ref}!{k_col}2:{k_col}"])
        get = lambda col, i: str(col[i]).strip() if i < len(col) else ""  # noqa: E731
        return [(get(keys, i), get(nums, i), get(results, i)) for i in range(max(len(nums), len(results), len(keys)))]

    # -- writing -------------------------------------------------------------------
    def _ensure_rows(self, tab: str, needed: int) -> None:
        props = self.c.tabs().get(self.names[tab], {})
        have = int((props.get("gridProperties") or {}).get("rowCount") or 0)
        if props and have < needed:
            self.c.batch_update([{"appendDimension": {"sheetId": props["sheetId"], "dimension": "ROWS",
                                                      "length": needed - have + 500}}])

    def rewrite(self, tab: str, rows: list[list]) -> None:
        self._ensure_rows(tab, len(rows) + 1)
        self.c.clear(f"{self.ref(tab)}!A2:{col_letter(len(TABS[tab]) - 1)}")
        for i in range(0, len(rows), 2000):
            self.c.update_values(f"{self.ref(tab)}!A{i + 2}", [[_cell(v) for v in r] for r in rows[i:i + 2000]])

    def append(self, tab: str, rows: list[list]) -> None:
        for i in range(0, len(rows), 500):
            self.c.append_values(f"{self.ref(tab)}!A1", [[_cell(v) for v in r] for r in rows[i:i + 500]])

    def set_lead_statuses(self, leads_tab: str, statuses: dict[str, str]) -> int:
        """Write the Status cell of leads by Key (row numbers are re-read, so a sorted Sheet stays correct)."""
        if not statuses:
            return 0
        ref = _tab_ref(leads_tab)
        head = self.c.get_values(f"{ref}!A1:AZ1")
        header = [h.strip() for h in (head[0] if head else [])]
        if "Key" not in header or "Status" not in header:
            return 0
        k_col, s_col = col_letter(header.index("Key")), col_letter(header.index("Status"))
        (keys,) = self.c.batch_get_columns([f"{ref}!{k_col}2:{k_col}"])
        data = [{"range": f"{ref}!{s_col}{i + 2}", "values": [[statuses[str(k).strip()]]]}
                for i, k in enumerate(keys) if str(k).strip() in statuses]
        for i in range(0, len(data), 300):
            self.c.batch_update_values(data[i:i + 300])
        return len(data)
