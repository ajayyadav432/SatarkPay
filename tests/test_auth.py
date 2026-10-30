"""Three logins. The server is what enforces them, so every check here goes straight at the API, as an attacker would."""
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from tests.conftest import TEST_PASSWORD
from ml.simulate import PERSONAS

SUNITA = PERSONAS["sunita"]["vpa"]
ADMIN_ONLY = [("get", "/api/v1/kpis"), ("get", "/api/v1/feed"), ("get", "/api/v1/alerts"), ("get", "/api/v1/alerts/1"), ("get", "/api/v1/graph?vpa=a@b"),
              ("post", "/api/v1/sim/start"), ("post", "/api/v1/sim/stop"), ("post", "/api/v1/sim/attack/fake_collect"), ("get", "/api/v1/join"), ("get", "/api/v1/stream")]


@pytest.fixture(autouse=True)
def fresh_tries(api):
    auth._fails.clear()
    yield
    auth._fails.clear()


def _client():
    return TestClient(app, base_url="http://192.168.1.20:8000", client=("192.168.1.50", 5000), follow_redirects=False)


def logged_in(role):
    c = _client()
    r = c.post("/api/v1/auth/login", json={"role": role, "username": auth.ACCOUNTS[role]["username"], "password": TEST_PASSWORD})
    assert r.status_code == 200
    return c


def test_password_hash_is_salted_and_checks():
    a, b = auth.hash_password("x"), auth.hash_password("x")
    assert a != b and "x" not in a.split(".")[0] and auth.check_password("x", a) and not auth.check_password("y", a)


@pytest.mark.parametrize("stored", [None, "", "plain", "scrypt.only", "md5.a.b", "scrypt.!!.!!"])
def test_a_broken_stored_hash_never_logs_in(stored):
    assert not auth.check_password("x", stored)


@pytest.mark.parametrize("role,username,password", [("admin", "admin", "wrong"), ("admin", "sunita", TEST_PASSWORD), ("user", "admin", TEST_PASSWORD), ("merchant", "", "")])
def test_wrong_details_are_refused_with_one_message(role, username, password):
    r = _client().post("/api/v1/auth/login", json={"role": role, "username": username, "password": password})
    assert r.status_code == 401 and r.json()["detail"] == "Wrong username or password."


def test_an_unknown_role_is_refused():
    assert _client().post("/api/v1/auth/login", json={"role": "root", "username": "a", "password": "b"}).status_code == 422


def _signup(c, **kw):
    return c.post("/api/v1/auth/signup", json={"role": "user", "username": "new.person", "password": "long-enough", "name": "New Person", **kw})


def test_sign_up_then_log_in_and_stay_in_your_portal():
    c = _client()
    name = "u" + __import__("secrets").token_hex(4)
    r = _signup(c, username=name)
    assert r.status_code == 200 and r.json()["home"] == "/pay"
    assert c.get("/api/v1/auth/me").json()["name"] == "New Person"
    assert c.get("/api/v1/kpis").status_code == 403
    assert _signup(_client(), username=name).status_code == 409, "a username can be taken only once"
    login = _client().post("/api/v1/auth/login", json={"role": "user", "username": name, "password": "long-enough"})
    assert login.status_code == 200
    assert _client().post("/api/v1/auth/login", json={"role": "user", "username": name, "password": "wrong-one"}).status_code == 401


def test_a_merchant_sign_up_keeps_its_shop_name():
    c = _client()
    name = "m" + __import__("secrets").token_hex(4)
    assert _signup(c, role="merchant", username=name, name="Asha Stores").json()["home"] == "/merchant"
    assert c.get("/api/v1/merchant/payments").json()["name"] == "Asha Stores"


def test_nobody_can_sign_up_as_admin():
    r = _signup(_client(), role="admin", username="evil.admin")
    assert r.status_code == 403
    assert _client().post("/api/v1/auth/login", json={"role": "admin", "username": "evil.admin", "password": "long-enough"}).status_code == 401


def test_demo_usernames_cannot_be_taken_by_sign_up():
    assert _signup(_client(), username="sunita").status_code == 409
    assert _signup(_client(), role="merchant", username="ramesh").status_code == 409


@pytest.mark.parametrize("bad", [{"username": "a"}, {"username": "has space"}, {"password": "short"}, {"name": " "}])
def test_bad_sign_ups_are_refused(bad):
    assert _signup(_client(), **bad).status_code == 422


@pytest.mark.parametrize("role,home", [("user", "/pay"), ("merchant", "/merchant"), ("admin", "/")])
def test_test_login_opens_each_portal_with_one_click(role, home):
    c = _client()
    r = c.post("/api/v1/auth/test-login", json={"role": role})
    assert r.status_code == 200 and r.json()["home"] == home
    assert c.get("/api/v1/auth/me").json()["role"] == role


def test_test_logins_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("SATARKPAY_TEST_LOGINS", "0")
    assert _client().post("/api/v1/auth/test-login", json={"role": "admin"}).status_code == 403
    assert _client().get("/api/v1/auth/options").json()["test_logins"] is False


def test_a_tampered_session_is_refused():
    token = _client().post("/api/v1/auth/test-login", json={"role": "user"}).json()["token"]
    import base64
    import json
    body, signature = token.split(".")
    forged = base64.urlsafe_b64encode(json.dumps({**json.loads(base64.urlsafe_b64decode(body)), "r": "admin"}).encode()).decode()
    assert _client().get("/api/v1/kpis", headers={"Authorization": f"Bearer {forged}.{signature}"}).status_code == 401
    assert _client().get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.token"}).status_code == 401


def test_a_session_survives_a_restart_when_the_secret_is_set(monkeypatch):
    monkeypatch.setenv("SATARK_SESSION_SECRET", "fixed-for-this-test")
    token = auth.test_login("user")
    auth._ended.clear()
    assert auth._read(token)["r"] == "user"
    monkeypatch.setenv("SATARK_SESSION_SECRET", "another-secret")
    assert auth._read(token) is None


def test_a_vercel_address_is_allowed_only_when_it_is_ours(monkeypatch):
    from app.main import _host_allowed
    assert not _host_allowed("satarkpay.vercel.app")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "satarkpay.vercel.app")
    assert _host_allowed("satarkpay.vercel.app") and not _host_allowed("evil.vercel.app")


def test_too_many_wrong_tries_lock_even_the_right_password():
    c = _client()
    for _ in range(auth.MAX_FAILS):
        assert c.post("/api/v1/auth/login", json={"role": "admin", "username": "admin", "password": "no"}).status_code == 401
    assert c.post("/api/v1/auth/login", json={"role": "admin", "username": "admin", "password": TEST_PASSWORD}).status_code == 429


def test_wrong_tries_on_one_account_do_not_lock_another():
    c = _client()
    for _ in range(auth.MAX_FAILS):
        c.post("/api/v1/auth/login", json={"role": "user", "username": "nobody.here", "password": "no"})
    assert c.post("/api/v1/auth/login", json={"role": "user", "username": "sunita", "password": TEST_PASSWORD}).status_code == 200


def test_the_browser_cookie_cannot_be_read_by_scripts():
    r = _client().post("/api/v1/auth/login", json={"role": "user", "username": "sunita", "password": TEST_PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_a_bearer_token_works_like_the_phone_app_sends_it():
    token = _client().post("/api/v1/auth/login", json={"role": "merchant", "username": "ramesh", "password": TEST_PASSWORD}).json()["token"]
    r = _client().get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 200 and r.json()["role"] == "merchant"
    assert _client().get("/api/v1/auth/me", headers={"Authorization": "Bearer made-up"}).status_code == 401


def test_logging_out_ends_the_session_for_real():
    token = _client().post("/api/v1/auth/login", json={"role": "admin", "username": "admin", "password": TEST_PASSWORD}).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert _client().post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert _client().get("/api/v1/kpis", headers=headers).status_code == 401


@pytest.mark.parametrize("method,path", ADMIN_ONLY)
def test_admin_routes_refuse_everyone_else(method, path):
    assert getattr(_client(), method)(path).status_code == 401
    assert getattr(logged_in("user"), method)(path).status_code == 403
    assert getattr(logged_in("merchant"), method)(path).status_code == 403


def test_alert_labels_are_admin_only():
    body = {"status": "false_alarm"}
    assert _client().patch("/api/v1/alerts/1", json=body).status_code == 401
    assert logged_in("user").patch("/api/v1/alerts/1", json=body).status_code == 403
    assert logged_in("merchant").patch("/api/v1/alerts/1", json=body).status_code == 403


def test_admin_can_read_the_dashboard_data():
    c = logged_in("admin")
    assert c.get("/api/v1/kpis").status_code == 200 and c.get("/api/v1/alerts").status_code == 200


@pytest.mark.parametrize("role,path,where", [(None, "/", "/login"), (None, "/pay", "/login"), (None, "/merchant", "/login"),
                                             ("user", "/", "/pay"), ("user", "/merchant", "/pay"), ("merchant", "/", "/merchant"), ("merchant", "/pay", "/merchant"),
                                             ("user", "/login", "/pay"), ("admin", "/login", "/")])
def test_pages_send_people_to_the_right_place(role, path, where):
    c = logged_in(role) if role else _client()
    r = c.get(path)
    assert r.status_code == 303 and r.headers["location"] == where


@pytest.mark.parametrize("role,path", [("user", "/pay"), ("merchant", "/merchant"), ("admin", "/"), ("admin", "/pay"), ("admin", "/merchant")])
def test_each_role_opens_its_own_pages(role, path):
    assert logged_in(role).get(path).status_code == 200


@pytest.mark.parametrize("path", ["/how", "/qr", "/go", "/login", "/api/health", "/api/v1/metrics"])
def test_public_pages_stay_public(path):
    assert _client().get(path).status_code == 200


def _pay(**kw):
    return {"payer": SUNITA, "payee": "ramesh.kirana@simaxis", "amount": 100, "kind": "QR", **kw}


def test_a_user_can_pay_only_from_a_demo_persons_account():
    c = logged_in("user")
    assert c.post("/api/v1/score", json=_pay()).status_code == 200
    assert c.post("/api/v1/score", json=_pay(payer="someone.else@simybl")).status_code == 403


def test_a_merchant_can_only_bring_in_payments_to_its_own_shop(engine):
    c = logged_in("merchant")
    assert c.post("/api/v1/score", json=_pay(payee=engine.persona_shop())).status_code == 200
    assert c.post("/api/v1/score", json=_pay(payee="other.shop@simybl")).status_code == 403


def test_nobody_can_listen_to_someone_elses_payments(engine):
    assert logged_in("user").get("/api/v1/stream/user/" + engine.persona_shop()).status_code == 403
    assert logged_in("merchant").get("/api/v1/stream/user/" + SUNITA).status_code == 403
    assert _client().get("/api/v1/stream/user/" + SUNITA).status_code == 401


def test_a_merchant_sees_only_its_own_shop(engine):
    c = logged_in("merchant")
    r = c.post("/api/v1/score", json=_pay(payee=engine.persona_shop(), record=True))
    assert r.status_code == 200
    d = c.get("/api/v1/merchant/payments").json()
    assert d["shop"] == engine.persona_shop() and d["received"] >= 1 and d["received_total"] > 0
    assert all(set(row) == {"txn_id", "time", "payer", "amount", "status", "action"} for row in d["rows"])
    assert logged_in("user").get("/api/v1/merchant/payments").status_code == 403


def test_a_login_from_another_website_is_refused():
    r = _client().post("/api/v1/auth/login", headers={"Origin": "https://evil.example"}, json={"role": "admin", "username": "admin", "password": TEST_PASSWORD})
    assert r.status_code == 403


def test_the_repo_holds_no_password_or_hash():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    assert "scrypt." not in (root / ".env.example").read_text()


def test_a_shops_takings_survive_the_live_feed_moving_on(engine):
    c = logged_in("merchant")
    assert c.post("/api/v1/score", json=_pay(payee=engine.persona_shop(), record=True)).status_code == 200
    before = c.get("/api/v1/merchant/payments").json()
    engine.feed.clear()
    after = c.get("/api/v1/merchant/payments").json()
    assert after["received"] == before["received"] >= 1 and after["received_total"] == before["received_total"] and after["rows"]



# --- reports, blocks, the feed, history ---------------------------------------------------

@pytest.fixture()
def clean(api):
    from app.payments import store
    store.clear_community()
    yield store
    store.clear_community()


def _member(name):
    c = _client()
    assert c.post("/api/v1/auth/signup", json={"role": "user", "username": name, "password": "long-enough", "name": name.title()}).status_code in (200, 409)
    assert c.post("/api/v1/auth/login", json={"role": "user", "username": name, "password": "long-enough"}).status_code == 200
    return c


def _score(c, payee="plain.person55@simybl", **kw):
    r = c.post("/api/v1/score", json={"payer": SUNITA, "payee": payee, "amount": 100, "kind": "QR", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_reports_from_three_accounts_warn_but_never_block(clean):
    payee = "reported.shop@simybl"
    for i in range(3):
        c = _member(f"reporter{i}")
        assert c.post("/api/v1/posts", json={"payee": payee, "category": "QR scam", "body": "This one asked me to scan to receive."}).status_code == 200
    d = _score(logged_in("user"), payee)
    assert d["reports"] == 3 and d["action"] == "WARN" and not d["blocked"]
    assert any("3 accounts" in x["text_en"] for x in d["reasons"])


def test_one_account_counts_once_however_often_it_reports(clean):
    c = _member("repeat.reporter")
    for _ in range(5):
        c.post("/api/v1/posts", json={"payee": "honest.shop@simybl", "category": "Other", "body": "I do not like this shop at all."})
    assert clean.report_count("honest.shop@simybl") == 1


def test_only_an_admin_can_block(clean):
    body = {"payee": "bad.one@simybl", "reason": "Confirmed by review"}
    assert _client().post("/api/v1/blocks", json=body).status_code == 401
    assert logged_in("user").post("/api/v1/blocks", json=body).status_code == 403
    assert logged_in("merchant").post("/api/v1/blocks", json=body).status_code == 403
    assert logged_in("admin").post("/api/v1/blocks", json=body).status_code == 200


def test_a_blocked_id_cannot_be_paid_even_by_calling_the_api(clean):
    logged_in("admin").post("/api/v1/blocks", json={"payee": "bad.one@simybl", "reason": "Confirmed by review"})
    c = logged_in("user")
    d = _score(c, "bad.one@simybl")
    assert d["action"] == "BLOCK" and d["blocked"] and d["reasons"][0]["id"] == "blocked"
    r = c.post("/api/v1/outcome", json={"txn_id": d["txn_id"], "token": d["token"], "decision": "paid"})
    assert r.status_code == 409


def test_an_unblocked_id_goes_back_to_normal(clean):
    a = logged_in("admin")
    a.post("/api/v1/blocks", json={"payee": "bad.one@simybl", "reason": "Confirmed by review"})
    assert a.delete("/api/v1/blocks/bad.one@simybl").status_code == 200
    assert not _score(logged_in("user"), "bad.one@simybl")["blocked"]


def test_a_public_test_admin_cannot_block_a_real_upi_id(clean):
    c = _client()
    c.post("/api/v1/auth/test-login", json={"role": "admin"})
    assert c.post("/api/v1/blocks", json={"payee": "someone.real@oksbi", "reason": "Trying it"}).status_code == 403
    assert c.post("/api/v1/blocks", json={"payee": "someone@simybl", "reason": "Trying it"}).status_code == 200
    assert logged_in("admin").post("/api/v1/blocks", json={"payee": "someone.real@oksbi", "reason": "Reviewed"}).status_code == 200


def test_the_feed_can_be_read_without_login_and_masks_real_details(clean):
    c = logged_in("user")
    c.post("/api/v1/posts", json={"payee": "someone.real@oksbi", "category": "QR scam", "body": "He called from 9876543210 and said pay victim.two@ybl or else"})
    p = _client().get("/api/v1/posts").json()["posts"][0]
    assert p["payee"] == "so***@oksbi"
    assert "9876543210" not in p["body"] and "victim.two" not in p["body"] and "vi***@ybl" in p["body"]
    assert _client().post("/api/v1/posts", json={"category": "Other", "body": "No login, no posting here."}).status_code == 401


def test_simulated_ids_stay_readable_in_the_feed(clean):
    logged_in("user").post("/api/v1/posts", json={"payee": "refund-sbi@simybl", "category": "Fake collect", "body": "This is the fake refund one."})
    assert _client().get("/api/v1/posts").json()["posts"][0]["payee"] == "refund-sbi@simybl"


def test_a_script_in_a_post_comes_back_as_plain_data_only(clean):
    body = '<img src=x onerror="alert(1)"> scam text'
    p = logged_in("user").post("/api/v1/posts", json={"category": "Other", "body": body}).json()
    assert p["body"] == body, "stored as text; the pages only ever show it as text"


@pytest.mark.parametrize("bad", [{"category": "Nope", "body": "A long enough body"}, {"category": "Other", "body": "short"}, {"category": "Other", "body": "x" * 1001},
                                 {"category": "Other", "body": "A long enough body", "payee": "not an id"}])
def test_bad_posts_are_refused(clean, bad):
    assert logged_in("user").post("/api/v1/posts", json=bad).status_code == 422


def test_one_account_has_one_vote_and_can_change_it(clean):
    c, d = _member("voter.one"), _member("voter.two")
    pid = c.post("/api/v1/posts", json={"category": "Other", "body": "A post people can vote on."}).json()["id"]
    assert c.post(f"/api/v1/posts/{pid}/vote", json={"value": 1}).json()["votes"] == 1
    assert c.post(f"/api/v1/posts/{pid}/vote", json={"value": 1}).json()["votes"] == 1
    assert d.post(f"/api/v1/posts/{pid}/vote", json={"value": 1}).json()["votes"] == 2
    assert c.post(f"/api/v1/posts/{pid}/vote", json={"value": -1}).json()["votes"] == 0
    assert c.post(f"/api/v1/posts/{pid}/vote", json={"value": 0}).json()["my_vote"] == 0
    assert c.post(f"/api/v1/posts/{pid}/vote", json={"value": 5}).status_code == 422
    assert c.post("/api/v1/posts/999999/vote", json={"value": 1}).status_code == 404


def test_top_sort_puts_the_most_voted_first(clean):
    c = _member("sorter")
    first = c.post("/api/v1/posts", json={"category": "Other", "body": "The first post in this feed."}).json()["id"]
    second = c.post("/api/v1/posts", json={"category": "Other", "body": "The second post in this feed."}).json()["id"]
    c.post(f"/api/v1/posts/{first}/vote", json={"value": 1})
    assert _client().get("/api/v1/posts?sort=new").json()["posts"][0]["id"] == second
    assert _client().get("/api/v1/posts?sort=top").json()["posts"][0]["id"] == first


def test_comments_are_saved_and_masked(clean):
    c = logged_in("user")
    pid = c.post("/api/v1/posts", json={"category": "Other", "body": "A post people can comment on."}).json()["id"]
    d = c.post(f"/api/v1/posts/{pid}/comments", json={"body": "He used 9876543210 with me too"}).json()
    assert len(d["comments"]) == 1 and "9876543210" not in d["comments"][0]["body"]
    assert _client().post(f"/api/v1/posts/{pid}/comments", json={"body": "No login"}).status_code == 401


def test_only_an_admin_can_hide_a_post(clean):
    pid = logged_in("user").post("/api/v1/posts", json={"category": "Other", "body": "A post an admin may hide."}).json()["id"]
    assert logged_in("user").delete(f"/api/v1/posts/{pid}").status_code == 403
    assert logged_in("admin").delete(f"/api/v1/posts/{pid}").status_code == 200
    assert _client().get("/api/v1/posts").json()["posts"] == []


def test_history_is_private_to_each_account(clean):
    a, b = _member("history.a"), _member("history.b")
    _score(a, "only.for.a@simybl")
    assert [x["subject"] for x in a.get("/api/v1/history").json()["checks"]] == ["only.for.a@simybl"]
    assert b.get("/api/v1/history").json()["checks"] == []
    assert b.get("/api/v1/history?everyone=true").status_code == 403
    assert logged_in("admin").get("/api/v1/history?everyone=true").json()["checks"]
    assert _client().get("/api/v1/history").status_code == 401


def test_history_can_be_searched_filtered_and_cleared(clean):
    c = _member("history.c")
    _score(c, "find.me@simybl")
    _score(c, "other.one@simybl")
    assert len(c.get("/api/v1/history?q=find").json()["checks"]) == 1
    assert c.get("/api/v1/history?action=BLOCK").json()["checks"] == []
    assert c.delete("/api/v1/history").status_code == 200
    assert c.get("/api/v1/history").json()["checks"] == []


def test_export_as_json_and_csv(clean):
    import csv
    import io
    import json
    c = _member("history.d")
    _score(c, "export.me@simybl", note="=HYPERLINK(1)")
    j = c.get("/api/v1/history/export.json")
    assert "attachment" in j.headers["content-disposition"] and json.loads(j.text)[0]["subject"] == "export.me@simybl"
    x = c.get("/api/v1/history/export.csv")
    rows = list(csv.DictReader(io.StringIO(x.text.lstrip("﻿"))))
    assert rows[0]["subject"] == "export.me@simybl"
    assert rows[0]["note"].startswith("'="), "a note must not run as a spreadsheet formula"
    assert c.get("/api/v1/history/export.xml").status_code == 422
    assert _client().get("/api/v1/history/export.csv").status_code == 401


def test_a_check_returns_the_real_stages(clean):
    d = _score(logged_in("user"), "olx.buyer.help@simybl", note="scan to receive", amount=5000)
    stages = {s["id"]: s["warn"] for s in d["stages"]}
    assert list(stages) == ["details", "upi_id", "words", "behaviour", "models", "decision"]
    assert stages["words"] and stages["decision"] and not stages["details"]
    quiet = {s["id"]: s["warn"] for s in _score(logged_in("user"), "ramesh.kirana@simaxis")["stages"]}
    assert not quiet["words"]
