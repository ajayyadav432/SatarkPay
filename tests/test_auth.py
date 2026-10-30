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

