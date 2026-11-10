"""An Outlook / Hotmail / Microsoft 365 mailbox, through Microsoft Graph.

Why not a password: Microsoft switched off password logins (and app passwords) for outlook.com mail apps in
September 2024; a program may only use the mailbox after the owner signs in once in the browser (OAuth). That is
`wr outlook-login N`: it shows a short code, the owner opens microsoft.com/devicelogin, types the code and signs in.
The sign-in is kept in secrets/outlook-N.json and renewed by itself.

It needs the owner's own free app registration (its "Application (client) ID" is OUTLOOK_CLIENT_ID in settings.txt;
docs/OUTLOOK.md walks through it) with the delegated permissions Mail.Send and Mail.ReadWrite.

Sending makes a draft from the finished e-mail (so Microsoft tells us the Message-ID it gives it, which the
follow-ups and the reply matching need) and then sends that draft.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from ..outreach.classify import bounced_addresses, classify_reply, is_bounce, new_text
from ..settings import secrets_dir
from .base import InboxEvent, Mailbox, SendResult

AUTHORITY = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Mail.ReadWrite"
# Graph error codes: the mailbox may not send for now (a limit) / at all (blocked as spam, suspended).
LIMIT_CODES = ("throttl", "toomanyrequests", "quotaexceeded", "exceededmessagelimit", "sendquota", "ratelimit",
               "messagelimit", "mailboxconcurrency")
BLOCK_CODES = ("submissionblocked", "accountsuspend", "senddenied", "outboundspam", "accountdisabled", "blocked")
INVALID_CODES = ("invalidrecipients", "recipientnotfound", "invalidrecipient")


class LoginNeeded(Exception):
    pass


def _session():
    import requests

    return requests.Session()


class GraphMailbox(Mailbox):
    kind = "outlook"

    def __init__(self, address: str, client_id: str, *, tenant: str = "common", index: int = 1, http=None,
                 token_path: str | os.PathLike | None = None, now_fn=time.time, sleep_fn=time.sleep,
                 timeout: float = 40):
        self.address = address.lower()
        self.client_id, self.tenant, self.index = client_id, tenant or "common", index
        self.http = http or _session()
        self.token_path = Path(token_path) if token_path else secrets_dir() / f"outlook-{index}.json"
        self.now, self.sleep, self.timeout = now_fn, sleep_fn, timeout
        self._token: dict | None = None

    # ------------------------------------------------------------------ sign-in
    def _load(self) -> dict:
        if self._token is None:
            try:
                self._token = json.loads(self.token_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._token = {}
        return self._token

    def _save(self, tok: dict) -> None:
        tok = {**tok, "expires_at": self.now() + int(tok.get("expires_in") or 3600) - 120}
        self._token = tok
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.token_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tok), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.token_path)

    def start_login(self) -> dict:
        """Step 1 of the browser sign-in: {user_code, verification_uri, device_code, interval, expires_in, message}."""
        r = self.http.post(f"{AUTHORITY}/{self.tenant}/oauth2/v2.0/devicecode",
                           data={"client_id": self.client_id, "scope": SCOPES}, timeout=self.timeout)
        data = _json(r)
        if r.status_code != 200 or "device_code" not in data:
            raise LoginNeeded(_oauth_error(data, r.status_code))
        return data

    def finish_login(self, flow: dict) -> None:
        """Step 2: wait until the owner has signed in with the code, then keep the sign-in."""
        deadline = self.now() + int(flow.get("expires_in") or 900)
        wait = max(2, int(flow.get("interval") or 5))
        while self.now() < deadline:
            self.sleep(wait)
            r = self.http.post(f"{AUTHORITY}/{self.tenant}/oauth2/v2.0/token", timeout=self.timeout,
                               data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                     "client_id": self.client_id, "device_code": flow["device_code"]})
            data = _json(r)
            if r.status_code == 200 and data.get("access_token"):
                self._save(data)
                return
            err = data.get("error", "")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                wait += 5
                continue
            raise LoginNeeded(_oauth_error(data, r.status_code))
        raise LoginNeeded("the code expired before the sign-in was finished - run the login again")

    def _access(self) -> str:
        tok = self._load()
        if tok.get("access_token") and float(tok.get("expires_at") or 0) > self.now():
            return tok["access_token"]
        if not tok.get("refresh_token"):
            raise LoginNeeded(f"{self.address} is not signed in yet: run  wr outlook-login {self.index}")
        r = self.http.post(f"{AUTHORITY}/{self.tenant}/oauth2/v2.0/token", timeout=self.timeout,
                           data={"grant_type": "refresh_token", "client_id": self.client_id,
                                 "refresh_token": tok["refresh_token"], "scope": SCOPES})
        data = _json(r)
        if r.status_code != 200 or not data.get("access_token"):
            if data.get("error") in ("invalid_grant", "interaction_required"):
                raise LoginNeeded(f"{self.address}: the sign-in has expired - run  wr outlook-login {self.index}  again")
            raise OSError(_oauth_error(data, r.status_code))
        data.setdefault("refresh_token", tok["refresh_token"])
        self._save(data)
        return data["access_token"]

    def _call(self, method: str, url: str, **kw):
        headers = {"Authorization": f"Bearer {self._access()}", **kw.pop("headers", {})}
        return self.http.request(method, url if url.startswith("http") else GRAPH + url, headers=headers,
                                 timeout=self.timeout, **kw)

    def check(self) -> str:
        try:
            r = self._call("GET", "/me?$select=mail,userPrincipalName")
        except LoginNeeded as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001 - no internet, DNS: say it plainly
            return f"{self.address}: could not reach Microsoft ({type(exc).__name__}: {exc})"
        if r.status_code != 200:
            return f"{self.address}: Microsoft refused ({r.status_code}: {_graph_error(r)[1][:160]})"
        me = _json(r)
        mine = {str(me.get("mail") or "").lower(), str(me.get("userPrincipalName") or "").lower()}
        if self.address not in mine and "#ext#" not in "".join(mine):
            return (f"signed in as {me.get('mail') or me.get('userPrincipalName')}, but settings.txt says "
                    f"{self.address}: sign in with that account (wr outlook-login {self.index})")
        return ""

    # ------------------------------------------------------------------ sending
    def send(self, msg: EmailMessage) -> SendResult:
        try:
            mime = base64.b64encode(msg.as_bytes())
            r = self._call("POST", "/me/messages", data=mime, headers={"Content-Type": "text/plain"})
            if r.status_code not in (200, 201):
                return self._failed(r)
            draft = _json(r)
            r2 = self._call("POST", f"/me/messages/{draft.get('id')}/send")
            if r2.status_code not in (200, 202):
                self._call("DELETE", f"/me/messages/{draft.get('id')}")     # no half-sent draft left behind
                return self._failed(r2)
            return SendResult("sent", msgid=str(draft.get("internetMessageId") or ""))
        except LoginNeeded as exc:
            return SendResult("auth", 401, str(exc))
        except Exception as exc:  # noqa: BLE001 - connection reset, DNS, timeout
            return SendResult("network", 0, f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _failed(r) -> SendResult:
        code, text = _graph_error(r)
        c = code.lower().replace("_", "")
        detail = f"{code}: {text}"[:300]
        if r.status_code == 401:
            return SendResult("auth", 401, detail)
        if r.status_code == 429 or any(k in c for k in LIMIT_CODES):
            return SendResult("limit", r.status_code, detail)
        if any(k in c for k in BLOCK_CODES) or "spam" in text.lower():
            return SendResult("blocked", r.status_code, detail)
        if any(k in c for k in INVALID_CODES):
            return SendResult("invalid", r.status_code, detail)
        if r.status_code in (403,):
            return SendResult("blocked", r.status_code, detail)
        return SendResult("temp", r.status_code, detail)

    # ------------------------------------------------------------------ reading
    def scan(self, *, known_emails: set[str], known_msgids: dict[str, str], cursor: dict,
             max_messages: int = 400) -> tuple[list[InboxEvent], dict]:
        since = cursor.get("since")
        if not since:           # first look: start from now, never read old mail
            return [], {"since": _iso(self.now())}
        url = ("/me/mailFolders/inbox/messages?$top=50&$orderby=receivedDateTime asc"
               f"&$filter=receivedDateTime gt {since}"
               "&$select=id,subject,from,receivedDateTime,internetMessageHeaders,body")
        events: list[InboxEvent] = []
        newest, seen = since, 0
        while url and seen < max_messages:
            r = self._call("GET", url, headers={"Prefer": 'outlook.body-content-type="text"'})
            if r.status_code != 200:
                raise OSError(f"Microsoft Graph {r.status_code}: {_graph_error(r)[1][:200]}")
            page = _json(r)
            for m in page.get("value") or []:
                seen += 1
                newest = max(newest, str(m.get("receivedDateTime") or newest))
                events.extend(self._consider(m, known_emails, known_msgids))
            url = page.get("@odata.nextLink") or ""
        return events, {"since": newest}

    def _consider(self, m: dict, known_emails: set[str], known_msgids: dict[str, str]) -> list[InboxEvent]:
        sender = str(((m.get("from") or {}).get("emailAddress") or {}).get("address") or "").lower()
        name = str(((m.get("from") or {}).get("emailAddress") or {}).get("name") or "")
        subject = str(m.get("subject") or "")
        h = {str(x.get("name") or "").lower(): str(x.get("value") or "") for x in m.get("internetMessageHeaders") or []}
        h.setdefault("from", f"{name} <{sender}>")
        refs = re.findall(r"<[^>]+>", h.get("in-reply-to", "") + " " + h.get("references", ""))
        bounce = is_bounce(h["from"], subject)
        thread_email = sender if sender in known_emails else next((known_msgids[r] for r in refs if r in known_msgids), "")
        if sender == self.address or not (bounce or thread_email):
            return []
        body = str((m.get("body") or {}).get("content") or "")
        ref = str(m.get("id") or "")
        if bounce:
            hits = bounced_addresses(h, body, known_emails)
            if not hits and thread_email:
                hits = {thread_email}
            return [InboxEvent("bounce", e, ref=ref) for e in sorted(hits)]
        return [InboxEvent("reply", thread_email, classify_reply(subject, body, h), new_text(body), ref)]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_minus(iso: str, seconds: int) -> str:
    t = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) - timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(r) -> dict:
    try:
        data = r.json()
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - an empty or non-JSON answer
        return {}


def _graph_error(r) -> tuple[str, str]:
    err = _json(r).get("error") or {}
    if isinstance(err, dict):
        return str(err.get("code") or r.status_code), str(err.get("message") or "")
    return str(r.status_code), str(err)


def _oauth_error(data: dict, status: int) -> str:
    desc = str(data.get("error_description") or data.get("error") or f"HTTP {status}").split("\r\n")[0]
    hint = ""
    if "AADSTS70002" in desc or "AADSTS7000218" in desc or "public client" in desc.lower():
        hint = ' - in the app registration, Authentication: set "Allow public client flows" to Yes'
    elif "AADSTS700016" in desc or "unauthorized_client" in str(data.get("error")):
        hint = (" - check OUTLOOK_CLIENT_ID, and that the app registration allows personal Microsoft accounts "
                "(for an outlook.com address)")
    return f"Microsoft sign-in failed: {desc[:220]}{hint}"
