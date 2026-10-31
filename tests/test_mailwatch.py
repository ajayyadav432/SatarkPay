"""The inbox watcher: only new mail, never changes the mailbox, and a broken e-mail cannot stop it."""
import email
import inspect
from email.message import EmailMessage
from email.policy import default as default_policy

import pytest

from app import config
from app.payments import mailwatch, store


def html_mail(subject, sender, html, msgid):
    m = EmailMessage(policy=default_policy)
    m["Subject"], m["From"], m["Message-ID"] = subject, sender, msgid
    m.set_content("This e-mail needs an HTML viewer.")
    m.add_alternative(html, subtype="html")
    return m


class FakeIMAP:
    def __init__(self, mails):
        self.mails = mails

    def select(self, box, readonly=False):
        assert readonly is True     # the watcher must never change the mailbox
        return "OK", [b"1"]

    def response(self, name):
        return "OK", [b"777"]

    def uid(self, cmd, *args):
        if cmd == "search":
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.mails))]
        assert "PEEK" in args[1]    # fetching must not mark mail as read
        return "OK", [(b"1 (BODY[] {n})", self.mails[int(args[0])]), b")"]


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(mailwatch, "STATE", tmp_path / "state.json")


def test_message_text_finds_hidden_links():
    m = email.message_from_bytes(bytes(html_mail("Account suspended", "PayPal <service@paypa1-secure.com>", '<p>Limited. <a href="http://paypa1.com/signin">Log in</a></p>', "<a@x>")), policy=default_policy)
    text, sender = mailwatch.message_text(m)
    assert sender == "service@paypa1-secure.com" and "Account suspended" in text
    assert "http://paypa1.com/signin" in text


def test_only_new_mail_is_checked_and_only_once(state):
    seen = []
    conn = FakeIMAP({1: bytes(html_mail("Old newsletter", "news@shop.example", "<p>Hello</p>", "<old@x>"))})
    on_mail = lambda *a: seen.append(a)  # noqa: E731
    assert mailwatch.check_once(conn, "me@test", on_mail) == 0     # first run: starts from now
    conn.mails[2] = bytes(html_mail("New", "a@b.example", "<p>Hi</p>", "<new@x>"))
    assert mailwatch.check_once(conn, "me@test", on_mail) == 1
    assert mailwatch.check_once(conn, "me@test", on_mail) == 0
    assert [s[2] for s in seen] == ["<new@x>"]


def test_a_broken_email_cannot_stop_the_watcher(state, monkeypatch):
    seen = []
    conn = FakeIMAP({1: b"Subject: old\r\n\r\nhi"})
    on_mail = lambda text, sender, ref: seen.append(ref)  # noqa: E731
    mailwatch.check_once(conn, "me@test", on_mail)
    real = mailwatch.message_text

    def read(msg):
        if "poison" in str(msg["subject"]):
            raise LookupError("unknown charset")
        return real(msg)

    monkeypatch.setattr(mailwatch, "message_text", read)
    conn.mails[2] = bytes(html_mail("poison", "a@b.example", "<p>x</p>", "<bad@x>"))
    conn.mails[3] = bytes(html_mail("fine", "a@b.example", "<p>x</p>", "<good@x>"))
    before = mailwatch.status["skipped"]
    assert mailwatch.check_once(conn, "me@test", on_mail) == 1
    assert seen == ["<good@x>"] and mailwatch.status["skipped"] == before + 1


def test_a_scam_email_is_scored_and_reaches_the_laptops_history(state):
    from app import main
    store.init()
    scam = html_mail("Your SBI account will be blocked", "alerts@sbi-kyc-update.xyz", '<p>Dear customer, update your KYC immediately <a href="http://sbi-kyc-update.xyz/login">here</a>.</p>', "<scam-watch@x>")
    conn = FakeIMAP({1: b"Subject: old\r\n\r\nhi"})
    mailwatch.check_once(conn, "me@test", main._mail_checked)
    conn.mails[2] = bytes(scam)
    assert mailwatch.check_once(conn, "me@test", main._mail_checked) == 1
    row = store.list_checks(None, None, "alerts@sbi-kyc-update.xyz", "", 5, ("EMAIL",), True)[0]
    assert row["subject"] == "alerts@sbi-kyc-update.xyz" and row["level"] in ("High", "Critical") and 0 <= row["score"] <= 100
    assert row["note"] == ""     # the words themselves are not kept


def test_the_servers_certificate_is_checked_because_the_password_is_sent():
    assert "ssl.create_default_context()" in inspect.getsource(mailwatch.connect)


def test_only_an_admin_sees_the_status_and_it_never_holds_the_password():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, base_url="http://192.168.1.20:8000", client=("192.168.1.50", 5000)) as c:
        assert c.get("/api/v1/mail-watch").status_code == 401
        assert c.post("/api/v1/auth/test-login", json={"role": "user"}).status_code == 200
        assert c.get("/api/v1/mail-watch").status_code == 403
        assert c.post("/api/v1/auth/test-login", json={"role": "admin"}).status_code == 200
        body = c.get("/api/v1/mail-watch").json()
    assert set(body) == {"enabled", "running", "last_check", "checked", "skipped", "error"}


def test_the_online_copy_does_not_watch_a_mailbox():
    assert config.ON_VERCEL is False
    from app import main
    source = inspect.getsource(main.lifespan)
    assert "not config.ON_VERCEL and not store.is_shared()" in source
