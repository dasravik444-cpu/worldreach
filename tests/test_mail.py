"""The mailboxes (SMTP/IMAP and Outlook through Microsoft Graph), the address checker, the text check."""
from __future__ import annotations

import base64
import email
import json
import smtplib
from email import policy

import pytest
from outreach_helpers import FakeMX, outreach_config

from worldreach import settings as S
from worldreach.mail import build_message, open_mailbox
from worldreach.mail.base import classify_smtp_error
from worldreach.mail.dnscheck import check_domain
from worldreach.mail.lint import lint
from worldreach.mail.outlook import GraphMailbox, LoginNeeded
from worldreach.mail.smtp import SmtpMailbox
from worldreach.mail.verify import Verifier
from worldreach.outreach import templates as T
from worldreach.outreach.classify import classify_reply, wants_overview
from worldreach.outreach.leads import Lead


def message(to="owner@biz.com", **kw):
    return build_message(sender_name="Ravik Das", sender_addr="me@gmail.com", to=to, subject="hello", body="Hi there", **kw)


# ------------------------------------------------------------------ SMTP / IMAP
class FakeSMTP:
    script: dict = {}
    sent: list = []
    logins: list = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def ehlo(self): pass
    def starttls(self, context=None): pass
    def quit(self): pass

    def login(self, user, password):
        FakeSMTP.logins.append((user, password))
        if password == "wrongpassword":
            raise smtplib.SMTPAuthenticationError(534, b"5.7.9 Application-specific password required")

    def send_message(self, msg):
        to = str(msg["To"])
        if to in FakeSMTP.script:
            code, text = FakeSMTP.script[to]
            raise smtplib.SMTPRecipientsRefused({to: (code, text.encode())})
        FakeSMTP.sent.append(msg)
        return {}


class FakeIMAP:
    def __init__(self, messages: dict[int, bytes], validity="7"):
        self.messages, self.validity = messages, validity

    def login(self, user, password): return "OK", []
    def select(self, box, readonly=False): return "OK", []
    def logout(self): pass

    def status(self, box, what):
        return "OK", [f'"INBOX" (UIDNEXT {max(self.messages, default=0) + 1} UIDVALIDITY {self.validity})'.encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            low = int(args[1].split()[1].split(":")[0])
            return "OK", [" ".join(str(u) for u in sorted(self.messages) if u >= low).encode()]
        uids = [int(u) for u in args[0].split(",")]
        if "HEADER.FIELDS" in args[1]:
            out = []
            for u in uids:
                raw = self.messages[u]
                out.append((f"{u} (UID {u} RFC822.SIZE {len(raw)} BODY[HEADER.FIELDS] {{1}}".encode(), raw.split(b"\n\n")[0]))
                out.append(b")")
            return "OK", out
        return "OK", [(f"{uids[0]} (BODY[] {{1}}".encode(), self.messages[uids[0]]), b")"]


def raw(frm, subject, body, **headers) -> bytes:
    lines = [f"From: {frm}", f"Subject: {subject}"] + [f"{k.replace('_', '-')}: {v}" for k, v in headers.items()]
    return ("\n".join(lines) + "\n\n" + body).encode()


def test_smtp_mailbox_sends_classifies_refusals_and_explains_a_wrong_password():
    FakeSMTP.script, FakeSMTP.sent, FakeSMTP.logins = {"gone@biz.com": (550, "5.1.1 user unknown"),
                                                       "full@biz.com": (550, "5.4.5 Daily user sending limit exceeded")}, [], []
    mb = SmtpMailbox("Me@Gmail.com", "abcd efgh ijkl mnop", smtp_factory=FakeSMTP)
    assert mb.check() == "" and FakeSMTP.logins[-1] == ("me@gmail.com", "abcdefghijklmnop")
    assert mb.send(message()).ok and len(FakeSMTP.sent) == 1
    assert mb.send(message("gone@biz.com")).status == "invalid"
    assert mb.send(message("full@biz.com")).status == "limit"
    bad = SmtpMailbox("me@gmail.com", "wrongpassword", smtp_factory=FakeSMTP)
    assert "app password" in bad.check() and bad.send(message()).status == "auth"


def test_smtp_errors_are_told_apart():
    assert classify_smtp_error(550, "5.7.1 message blocked: unsolicited mail, spam policy") == "blocked"
    assert classify_smtp_error(421, "4.7.0 temporary rate limit") == "limit"
    assert classify_smtp_error(554, "5.2.252 SendAsDenied; exceeded sending limit") == "limit"
    assert classify_smtp_error(451, "4.3.0 try again later") == "temp"
    assert classify_smtp_error(550, "5.1.1 no such user") == "invalid"


def test_the_message_is_plain_text_with_an_unsubscribe_header_and_keeps_the_conversation():
    m = message(in_reply_to="<a@gmail.com>", references=["<a@gmail.com>"])
    assert m.get_content_type() == "text/plain" and m["List-Unsubscribe"] == "<mailto:me@gmail.com?subject=unsubscribe>"
    assert m["In-Reply-To"] == "<a@gmail.com>" and m["Message-ID"].endswith("@gmail.com>")
    assert "http" not in m.as_string().split("\n\n", 1)[1]


def test_imap_scan_reads_only_what_concerns_us_and_starts_from_now():
    msgs = {5: raw("old@x.com", "old", "before we started")}
    imap = FakeIMAP(msgs)
    mb = SmtpMailbox("me@gmail.com", "x", imap_factory=lambda: imap)
    events, cursor = mb.scan(known_emails={"owner@biz.com"}, known_msgids={}, cursor={})
    assert events == [] and cursor == {"uid": 5, "validity": "7"}          # the first look reads nothing old
    msgs[6] = raw("Dana <owner@biz.com>", "Re: hello", "Yes please, send it.\n\nOn Mon, Ravik wrote:\n> Hi there")
    msgs[7] = raw("friend@private.com", "lunch?", "private mail, never opened")
    msgs[8] = raw("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "Delivery Status Notification (Failure)",
                  "Address not found: gone@biz.com does not exist", X_Failed_Recipients="gone@biz.com")
    msgs[9] = raw("other@biz2.com", "Re: hi", "No thanks, remove us.", In_Reply_To="<m1@gmail.com>")
    msgs[10] = raw("owner@biz3.com", "Automatic reply: hello", "I am out of the office.", Auto_Submitted="auto-replied")
    events, cursor = mb.scan(known_emails={"owner@biz.com", "gone@biz.com", "owner@biz3.com", "first@biz2.com"},
                             known_msgids={"<m1@gmail.com>": "first@biz2.com"}, cursor=cursor)
    got = {(e.kind, e.email, e.reply_kind) for e in events}
    assert got == {("reply", "owner@biz.com", "positive"), ("bounce", "gone@biz.com", ""),
                   ("reply", "first@biz2.com", "negative"), ("reply", "owner@biz3.com", "auto")}
    assert next(e for e in events if e.email == "owner@biz.com").text == "Yes please, send it."
    assert cursor["uid"] == 10


# ------------------------------------------------------------------ Outlook (Microsoft Graph)
class Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._p = status, payload or {}
        self.text = json.dumps(self._p)

    def json(self):
        return self._p


class FakeGraph:
    """Microsoft's sign-in and Graph mail endpoints, as far as the mailbox uses them."""

    def __init__(self):
        self.calls, self.drafts, self.sent, self.inbox = [], {}, [], []
        self.pending, self.fail_send, self.refresh_ok = 1, None, True

    def post(self, url, data=None, timeout=None):
        return self.request("POST", url, data=data)

    def request(self, method, url, headers=None, data=None, timeout=None, **kw):
        self.calls.append((method, url))
        if url.endswith("/devicecode"):
            return Resp(200, {"device_code": "dev", "user_code": "ABCD-1234", "interval": 1, "expires_in": 900,
                              "verification_uri": "https://microsoft.com/devicelogin"})
        if url.endswith("/token"):
            if data.get("grant_type") == "refresh_token":
                return Resp(200, {"access_token": "at2", "expires_in": 3600}) if self.refresh_ok else \
                    Resp(400, {"error": "invalid_grant", "error_description": "AADSTS70000: expired"})
            if self.pending:
                self.pending -= 1
                return Resp(400, {"error": "authorization_pending"})
            return Resp(200, {"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600})
        assert (headers or {}).get("Authorization", "").startswith("Bearer at")
        if url.endswith("/me?$select=mail,userPrincipalName"):
            return Resp(200, {"mail": "me@outlook.com", "userPrincipalName": "me@outlook.com"})
        if method == "POST" and url.endswith("/me/messages"):
            assert headers["Content-Type"] == "text/plain"
            msg = email.message_from_bytes(base64.b64decode(data), policy=policy.default)
            mid = f"d{len(self.drafts) + 1}"
            self.drafts[mid] = msg
            return Resp(201, {"id": mid, "internetMessageId": f"<{mid}@outlook.com>"})
        if method == "POST" and url.endswith("/send"):
            if self.fail_send:
                return Resp(*self.fail_send)
            self.sent.append(self.drafts[url.split("/")[-2]])
            return Resp(202)
        if method == "DELETE":
            self.drafts.pop(url.split("/")[-1], None)
            return Resp(204)
        if method == "GET" and "/mailFolders/inbox/messages" in url:
            assert headers["Prefer"] == 'outlook.body-content-type="text"'
            return Resp(200, {"value": self.inbox})
        return Resp(404, {"error": {"code": "NotFound", "message": url}})


def graph_message(frm, subject, body, when="2027-02-01T16:00:00Z", headers=None):
    return {"id": f"id-{frm}", "subject": subject, "receivedDateTime": when, "body": {"content": body},
            "from": {"emailAddress": {"address": frm, "name": frm.split("@")[0]}},
            "internetMessageHeaders": [{"name": k, "value": v} for k, v in (headers or {}).items()]}


def test_outlook_signs_in_with_a_code_sends_through_a_draft_and_reads_replies(tmp_path):
    g = FakeGraph()
    clock = [1_800_000_000.0]
    mb = GraphMailbox("me@outlook.com", "client-id", http=g, token_path=tmp_path / "outlook-2.json", index=2,
                      now_fn=lambda: clock[0], sleep_fn=lambda s: clock.__setitem__(0, clock[0] + s))
    assert mb.send(message()).status == "auth" and "wr outlook-login 2" in mb.check()      # not signed in yet
    flow = mb.start_login()
    assert flow["user_code"] == "ABCD-1234"
    mb.finish_login(flow)
    assert json.loads((tmp_path / "outlook-2.json").read_text())["refresh_token"] == "rt1"
    assert oct((tmp_path / "outlook-2.json").stat().st_mode)[-3:] == "600"
    assert mb.check() == ""
    res = mb.send(message("owner@biz.com"))
    assert res.ok and res.msgid == "<d1@outlook.com>" and str(g.sent[0]["To"]) == "owner@biz.com"
    assert g.sent[0]["List-Unsubscribe"] and g.sent[0].get_content().strip() == "Hi there"
    # the sign-in renews by itself after an hour
    clock[0] += 4000
    assert mb.send(message("two@biz.com")).ok and ("POST", "https://login.microsoftonline.com/common/oauth2/v2.0/token") in g.calls
    # limits and blocks are told apart; a failed send leaves no draft behind
    g.fail_send = (429, {"error": {"code": "ApplicationThrottled", "message": "Too many requests"}})
    assert mb.send(message("three@biz.com")).status == "limit" and len(g.drafts) == 2
    g.fail_send = (403, {"error": {"code": "ErrorMessageSubmissionBlocked", "message": "account flagged for outbound spam"}})
    assert mb.send(message("four@biz.com")).status == "blocked"
    g.fail_send = None
    # reading: first look starts from now; then replies and bounces of our conversations only
    events, cursor = mb.scan(known_emails={"owner@biz.com"}, known_msgids={}, cursor={})
    assert events == [] and cursor["since"].endswith("Z")
    g.inbox = [graph_message("owner@biz.com", "Re: hello", "Sure, tell me more."),
               graph_message("stranger@x.com", "hi", "not ours"),
               graph_message("postmaster@outlook.com", "Undeliverable: hello", "Delivery has failed to gone@biz.com",
                             when="2027-02-01T17:00:00Z")]
    events, cursor = mb.scan(known_emails={"owner@biz.com", "gone@biz.com"}, known_msgids={}, cursor=cursor)
    assert {(e.kind, e.email, e.reply_kind) for e in events} == {("reply", "owner@biz.com", "positive"),
                                                                 ("bounce", "gone@biz.com", "")}
    assert cursor == {"since": "2027-02-01T17:00:00Z"}
    # an expired sign-in asks for a new one, plainly
    g.refresh_ok = False
    clock[0] += 4000
    res = mb.send(message())
    assert res.status == "auth" and "wr outlook-login 2" in res.detail
    with pytest.raises(LoginNeeded):
        mb._access()


def test_mailboxes_come_from_the_settings(tmp_path, monkeypatch):
    f = tmp_path / "settings.txt"
    f.write_text("SENDER_NAME=Ravik\nMAILBOX_1=gmail\nMAILBOX_1_ADDRESS=a@gmail.com\nMAILBOX_1_PASSWORD=abcd efgh\n"
                 "MAILBOX_2=outlook\nMAILBOX_2_ADDRESS=b@outlook.com\nOUTLOOK_CLIENT_ID=cid-1\n"
                 "MAILBOX_3=smtp\nMAILBOX_3_ADDRESS=hello@mydomain.com\nMAILBOX_3_PASSWORD=pw\n"
                 "MAILBOX_3_SMTP_HOST=smtp.zoho.com\nMAILBOX_3_IMAP_HOST=imap.zoho.com\nMAILBOX_3_MAX_PER_DAY=150\n"
                 "MAILBOX_4=gmail\nMAILBOX_4_ADDRESS=c@gmail.com\n# a comment\nMARKETS=us, gb\n")
    monkeypatch.setenv("WR_SECRETS_DIR", str(tmp_path))
    st = S.load(f, env={})
    boxes = S.mailboxes(st)
    assert [(b.index, b.kind, b.address) for b in boxes] == [(1, "gmail", "a@gmail.com"), (2, "outlook", "b@outlook.com"),
                                                             (3, "smtp", "hello@mydomain.com"), (4, "gmail", "c@gmail.com")]
    assert boxes[0].password == "abcdefgh" and boxes[0].smtp_host == "smtp.gmail.com"
    assert [b.problem() for b in boxes[:3]] == ["", "", ""] and "PASSWORD is missing" in boxes[3].problem()
    assert boxes[2].max_per_day == 150
    assert isinstance(open_mailbox(boxes[1]), GraphMailbox) and isinstance(open_mailbox(boxes[2]), SmtpMailbox)
    from worldreach.outreach import config as C

    assert C.load(settings=st)["markets"] == ["us", "gb"]


# ------------------------------------------------------------------ the address checker and the text check
def test_addresses_that_would_bounce_or_annoy_are_refused_before_sending():
    v = Verifier(mx=FakeMX(dead=["deadsite.com"]))
    assert v.check("owner@goodgym.com") == ("ok", "")
    assert v.check("info@goodgym.com")[0] == "ok"                  # a small business's info@ is its inbox
    for bad in ("noreply@goodgym.com", "owner@gmial.com", "owner@deadsite.com", "x@mailinator.com", "not-an-address",
                "you@yourdomain.com", "postmaster@goodgym.com", "privacy@goodgym.com"):
        assert v.check(bad)[0] == "bad", bad
    assert v.check("careers@goodgym.com")[0] == "risky"


def test_every_email_we_can_send_passes_our_own_spam_check():
    from worldreach.cli import sample_leads, text_problems
    from outreach_helpers import markets

    o = outreach_config()
    ms = markets("us", "gb", "ie")
    assert text_problems(o, ms) == []
    assert len({T.first_email(ld, o)[1] for ld in sample_leads(ms)}) >= 15       # the wording really differs
    # and the check does catch what it should
    assert lint("FREE OFFER!!!", "Click here http://x.com to buy now. Guaranteed, only $99!", footer="")


def test_us_emails_carry_the_postal_address_and_a_way_to_say_no():
    o = outreach_config()
    lead = Lead(key="k1", lead_id="AUS-1", business="Lotus Yoga", category_key="studio", emails=["a@b.com"],
                market="us", country="US", tz="America/Chicago", city="Austin", person="Maria Lopez (owner)",
                usp="Small classes, never more than twelve mats since 2011")
    subject, body = T.first_email(lead, o)
    assert body.startswith("Hi Maria,") and '"Small classes, never more than twelve mats since 2011"' in body
    assert "12 Park Street, Kolkata 700016, India" in body and 'Reply "no" and I won\'t write again.' in body
    assert "business offer from Aurenflow. Not interested?" in body and "Lotus Yoga" in subject
    assert T.category_group("martial_arts") == "martial" and T.category_group("salon") == "salon"
    assert "students" in T.first_email(Lead(key="k2", business="Tiger Karate", category_key="martial_arts",
                                            country="US", market="us"), o)[1]


def test_only_a_clear_yes_gets_the_overview_automatically():
    for yes in ("Yes", "yes please", "Sure, send it over", "Sounds good, please send the overview",
                "Interested. Send me details", "ok", "Tell me more", "Please send more information"):
        assert wants_overview(yes), yes
    for other in ("Not sure what this is", "No thanks", "How did you get this address?", "We already have a system",
                  "Who are you?", "", "What does it cost? I don't want a subscription", "stop"):
        assert not wants_overview(other), other
    assert classify_reply("Re: x", "Unsubscribe me please") == "negative"
    assert classify_reply("Re: x", "How much is it?") == "positive"
    assert classify_reply("Automatic reply", "I'm away") == "auto"


def test_dns_check_tells_what_a_sending_domain_is_missing():
    class R:
        def __init__(self, records):
            self.records = records

        def resolve(self, name, kind):
            if (name, kind) not in self.records:
                raise LookupError(name)
            return self.records[(name, kind)]

    class Txt:
        def __init__(self, s):
            self.strings = [s.encode()]

    class Mx:
        exchange = "aspmx.l.google.com."

    good = R({("mydomain.com", "MX"): [Mx()], ("mydomain.com", "TXT"): [Txt("v=spf1 include:_spf.google.com ~all")],
              ("google._domainkey.mydomain.com", "TXT"): [Txt("v=DKIM1; k=rsa; p=MIIB")],
              ("_dmarc.mydomain.com", "TXT"): [Txt("v=DMARC1; p=none")]})
    assert all(ok for _, ok, _ in check_domain("mydomain.com", good))
    bare = {what: ok for what, ok, _ in check_domain("hello@bare.com", R({("bare.com", "MX"): [Mx()]}))}
    assert bare == {"MX": True, "SPF": False, "DKIM": False, "DMARC": False}
    assert check_domain("someone@gmail.com")[0][1] is True
