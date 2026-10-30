"""The whole story in a real (headless) browser, against the real server.

Skipped automatically when Playwright or its Chromium is not installed:
    .venv/bin/python -m pip install -r requirements-dev.txt && .venv/bin/python -m playwright install chromium
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed")
ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.e2e
E2E_PASSWORD = "e2e-test-password"
USERNAMES = {"user": "sunita", "merchant": "ramesh", "admin": "admin"}


def log_in(ctx, base, role):
    r = ctx.request.post(base + "/api/v1/auth/login", data={"role": role, "username": USERNAMES[role], "password": E2E_PASSWORD})
    assert r.status == 200, r.text()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    port = _free_port()
    from app import auth
    hashed = auth.hash_password(E2E_PASSWORD)
    env = dict(os.environ, SATARK_PASS_USER=hashed, SATARK_PASS_MERCHANT=hashed, SATARK_PASS_ADMIN=hashed, SATARKPAY_DB=str(tmp_path_factory.mktemp("e2e") / "e2e.db"), SATARKPAY_LIVE_USERS="1200", SATARKPAY_AUTOSTART="1")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            urllib.request.urlopen(url + "/api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("the server did not start: " + proc.stdout.read().decode()[:2000])
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def pw():
    with playwright_api.sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(pw):
    try:
        # SATARKPAY_E2E_CDP=http://127.0.0.1:9333 runs these in an already open Google Chrome.
        cdp = os.environ.get("SATARKPAY_E2E_CDP")
        b = pw.chromium.connect_over_cdp(cdp) if cdp else pw.chromium.launch()
    except Exception as exc:
        pytest.skip(f"Chromium is not installed: {exc}")
    yield b
    b.close()


@pytest.fixture()
def problems():
    return []


@pytest.fixture()
def desktop(browser, base, problems):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    log_in(ctx, base, "admin")
    page = ctx.new_page()
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    yield page
    ctx.close()


@pytest.fixture()
def phone(browser, base, problems):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    log_in(ctx, base, "admin")
    page = ctx.new_page()
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    yield page
    ctx.close()


def open_phone(phone, base):
    """The home screen. A request left over from an earlier test is answered first, as a person would."""
    phone.goto(base + "/pay")
    phone.wait_for_selector("[data-scenario=shop], #verdict")
    while phone.locator("#verdict").count():
        phone.click("#btn-cancel")
        phone.wait_for_selector("#done")
        phone.click("#btn-again")
        phone.wait_for_selector("[data-scenario=shop], #verdict")


def test_a_normal_payment_goes_through(phone, base, problems):
    open_phone(phone, base)
    phone.click("[data-scenario=shop]")
    phone.wait_for_selector("#verdict")
    assert phone.locator("#verdict").get_attribute("data-action") == "ALLOW"
    phone.click("#btn-pay")
    phone.wait_for_selector("#done")
    assert phone.locator("#done").get_attribute("data-decision") == "paid"
    assert not problems, problems


def test_a_fake_refund_is_stopped_and_explained_in_two_languages(phone, base, problems):
    open_phone(phone, base)
    phone.click("[data-scenario=fake_collect]")
    phone.wait_for_selector("#verdict")
    assert phone.locator("#verdict").get_attribute("data-action") in ("HOLD", "BLOCK")
    english = phone.inner_text("#reasons")
    assert "never receives" in english and "Refund of Rs 2999" in english
    assert phone.locator("a[href='tel:1930']").count() == 1
    phone.click("#lang button:nth-child(2)")
    assert "रोक" in phone.inner_text("#verdict-title")
    assert any("ऀ" <= ch <= "ॿ" for ch in phone.inner_text("#reasons"))
    phone.click("#btn-report")
    phone.wait_for_selector("#report-count")
    phone.click("#lang button:nth-child(1)")
    assert not problems, problems


def test_a_report_protects_the_next_person(phone, base):
    open_phone(phone, base)
    phone.click("[data-scenario=qr]")
    phone.wait_for_selector("#verdict")
    phone.click("#btn-report")
    phone.wait_for_selector("#report-count")
    assert "report" in phone.inner_text("#report-count")


def test_a_warning_lets_the_person_continue_only_after_a_pause(phone, base):
    open_phone(phone, base)
    phone.click("text=Beat the model")
    phone.fill("#beat-payee", "just.a.tiny.fee@simybl")
    phone.fill("#beat-amount", "1500")
    phone.fill("#beat-note", "processing fee")
    phone.click("#beat-go")
    phone.wait_for_selector("#verdict")
    if phone.locator("#btn-anyway").count():
        assert phone.locator("#btn-anyway").is_disabled(), "no instant click-through: the pause breaks the scammer's pressure"


def test_a_script_in_a_note_stays_plain_text(phone, base, problems):
    open_phone(phone, base)
    phone.click("text=Beat the model")
    phone.fill("#beat-payee", "xss.check.acct@simybl")
    phone.fill("#beat-amount", "2500")
    phone.fill("#beat-note", '<img src=x onerror="window.__xss=1"><script>window.__xss=1</script>')
    phone.click("#beat-go")
    phone.wait_for_selector("#verdict")
    assert phone.evaluate("window.__xss === undefined")
    assert phone.locator(".phone img").count() == 0 and phone.locator(".phone script").count() == 0
    assert "<img" in phone.inner_text(".pay-note")
    assert not problems, problems


def test_bad_input_shows_a_message_not_a_crash(phone, base):
    open_phone(phone, base)
    phone.click("text=Beat the model")
    phone.fill("#beat-payee", "not a upi id")
    phone.fill("#beat-amount", "100")
    phone.click("#beat-go")
    phone.wait_for_selector("#beat-error:not(.hidden)")
    assert "UPI ID" in phone.inner_text("#beat-error")


def test_an_attack_on_the_dashboard_reaches_the_open_phone(desktop, phone, base, problems):
    open_phone(phone, base)
    desktop.goto(base + "/")
    desktop.wait_for_selector("[data-attack=fake_collect]")
    phone.wait_for_timeout(600)      # the phone's live connection is open
    desktop.click("[data-attack=fake_collect]")
    phone.wait_for_selector("#verdict", timeout=30000)
    assert phone.locator("#verdict").get_attribute("data-action") in ("WARN", "HOLD", "BLOCK")
    assert "refund-sbi" in phone.inner_text(".pay-to")
    phone.click("#btn-report")
    phone.wait_for_selector("#report-count")
    assert not problems, problems


def test_a_request_is_not_lost_while_the_person_is_on_another_screen(desktop, phone, base, problems):
    """Found in code review: a request arriving away from the home screen vanished."""
    open_phone(phone, base)
    phone.click("[data-scenario=shop]")
    phone.wait_for_selector("#verdict")     # away from the home screen
    desktop.goto(base + "/")
    desktop.wait_for_selector("[data-attack=fake_collect]")
    phone.wait_for_timeout(600)
    desktop.click("[data-attack=fake_collect]")
    desktop.wait_for_timeout(4000)
    assert "refund-sbi" not in phone.inner_text(".pay-to"), "it does not interrupt"
    phone.click("#btn-pay")
    phone.wait_for_selector("#done")
    phone.click("#btn-again")
    phone.wait_for_selector("#verdict", timeout=30000)
    assert "refund-sbi" in phone.inner_text(".pay-to"), "it is waiting for them on the way back"
    assert not problems, problems


def test_the_dashboard_updates_live_and_explains_an_alert(desktop, base, problems):
    desktop.goto(base + "/")
    desktop.wait_for_selector("[data-attack=mule_ring]")
    desktop.wait_for_selector("#feed tr", timeout=15000)
    desktop.click("[data-attack=mule_ring]")
    desktop.wait_for_selector(".alert-item", timeout=30000)
    desktop.wait_for_selector("#detail .reasons li", timeout=30000)
    desktop.wait_for_selector("#graph svg", timeout=30000)
    assert desktop.locator(".shap-row").count() > 2
    assert "null" not in desktop.inner_text("#detail") and "undefined" not in desktop.inner_text("#detail")
    assert desktop.inner_text("#live-label").startswith("Live")
    desktop.click(".alert-item")
    desktop.click("#detail button:has-text('Confirm scam')")
    desktop.wait_for_selector("#detail button:has-text('Confirmed scam')")
    assert not problems, problems


def test_pausing_and_changing_speed(desktop, base):
    desktop.goto(base + "/")
    desktop.wait_for_selector("#btn-run")
    desktop.select_option("#speed", "100")
    desktop.click("#btn-run")
    for _ in range(40):
        if "Paused" in desktop.inner_text("#live-label"):
            break
        desktop.wait_for_timeout(250)
    assert "Paused" in desktop.inner_text("#live-label")
    desktop.click("#btn-run")
    desktop.select_option("#speed", "25")


def test_the_model_card_shows_measured_numbers_and_limits(desktop, base, problems):
    desktop.goto(base + "/how")
    desktop.wait_for_selector("h1")
    text = desktop.inner_text("#how")
    for phrase in ("Everything here is synthetic", "Scams it has never seen", "Why accuracy is the wrong number", "Known limits", "PaySim", "Honest people who look suspicious"):
        assert phrase in text, phrase
    assert "NaN" not in text and "undefined" not in text
    assert not problems, problems


def test_the_merchant_sees_what_really_arrived(desktop, base, problems):
    desktop.goto(base + "/merchant")
    desktop.wait_for_selector("#btn-customer")
    desktop.wait_for_timeout(600)
    desktop.click("#btn-customer")
    desktop.wait_for_selector("#rows tr", timeout=15000)
    assert int(desktop.inner_text("#n")) >= 1 and desktop.inner_text("#total") != "₹0"     # the live stream may pay this shop too
    assert "Received" in desktop.inner_text("#rows")
    assert not problems, problems


@pytest.mark.parametrize("path", ["/", "/pay", "/merchant", "/qr", "/how", "/go?u=http://sbi-kyc-update.xyz/login"])
def test_nothing_scrolls_sideways_on_a_phone(phone, base, path, problems):
    phone.goto(base + path)
    phone.wait_for_timeout(900)
    assert phone.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), path
    assert not problems, problems


def test_the_warning_page_still_works(desktop, base, problems):
    desktop.goto(base + "/go?u=http://sbi-kyc-update.xyz/login")
    desktop.wait_for_selector("#go-actions a")
    assert "sbi-kyc-update[.]xyz" in desktop.inner_text("#go-url")
    assert not problems, problems


ATTACKS = ["fake_collect", "phishing_link", "mule_ring", "takeover", "coached"]
SCENARIOS = ["shop", "fake_collect", "phishing", "qr", "mule", "coached", "p2p_collect"]


@pytest.mark.parametrize("name", ATTACKS)
def test_every_attack_button_shows_a_result_and_is_flagged(desktop, base, name, problems):
    desktop.goto(base + "/")
    desktop.wait_for_selector(f"[data-attack={name}]")
    desktop.click(f"[data-attack={name}]")
    slot = f"#attack-result-{name}"
    desktop.wait_for_function("s => /[1-9]\\d* flagged/.test(document.querySelector(s).textContent)", arg=slot, timeout=60000)
    assert "NaN" not in desktop.inner_text(slot) and "undefined" not in desktop.inner_text(slot)
    assert not problems, problems


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_phone_scenario_gets_the_right_kind_of_decision(phone, base, scenario, problems):
    open_phone(phone, base)
    phone.click(f"[data-scenario={scenario}]")
    phone.wait_for_selector("#verdict")
    action = phone.locator("#verdict").get_attribute("data-action")
    if scenario == "shop":
        assert action == "ALLOW"
    else:
        assert action in ("WARN", "HOLD", "BLOCK"), f"{scenario} got {action}"
        assert phone.inner_text("#reasons").strip(), "a stopped payment always says why"
    assert not problems, problems


def test_a_stopped_payment_never_counts_as_money_lost(phone, base):
    open_phone(phone, base)
    phone.click("[data-scenario=mule]")
    phone.wait_for_selector("#verdict")
    assert phone.locator("#verdict").get_attribute("data-action") in ("HOLD", "BLOCK")
    phone.click("#btn-cancel")
    phone.wait_for_selector("#done")
    assert phone.locator("#done").get_attribute("data-decision") != "paid"


def test_the_extension_warns_on_a_dangerous_page_in_a_real_browser(pw, tmp_path):
    """Uses Playwright's Chromium: branded Chrome no longer loads an unpacked extension from the command line."""
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=1)
    except OSError:
        pytest.skip("the extension only talks to port 8000: start ./run.sh first")
    ext = str(ROOT / "extension")
    try:
        ctx = pw.chromium.launch_persistent_context(str(tmp_path), channel="chromium", args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"])
    except Exception as exc:
        pytest.skip(f"Chromium is not installed: {exc}")
    try:
        page = ctx.new_page()
        page.route("http://sbi-kyc-update.xyz/**", lambda r: r.fulfill(status=200, content_type="text/html", body="<h1>KYC</h1>"))
        page.goto("http://sbi-kyc-update.xyz/login")
        page.wait_for_selector("#satark-page-bar", timeout=15000)
        assert "looks dangerous" in page.inner_text("#satark-page-bar")
    finally:
        ctx.close()


def test_the_test_qr_page_shows_a_readable_code_for_each_case(desktop, base, problems):
    desktop.goto(base + "/qr")
    desktop.wait_for_selector("[data-qr=phishing] img")
    desktop.wait_for_load_state("networkidle")
    sizes = desktop.eval_on_selector_all("[data-qr] img", "els => els.map(e => e.naturalWidth)")
    assert len(sizes) == 5 and all(w > 0 for w in sizes)
    assert not problems, problems


@pytest.mark.parametrize("role,home", [("user", "/pay"), ("merchant", "/merchant"), ("admin", "/")])
def test_each_login_lands_on_its_own_screen(browser, base, role, home):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(base + "/")
    page.wait_for_url("**/login")
    page.click(f"[data-role={role}]")
    page.fill("#username", USERNAMES[role])
    page.fill("#password", E2E_PASSWORD)
    page.click("#btn-login")
    page.wait_for_url(base + home)
    page.wait_for_selector("#btn-logout")
    page.click("#btn-logout")
    page.wait_for_url("**/login")
    ctx.close()


def test_a_wrong_password_shows_a_message(browser, base):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(base + "/login")
    page.fill("#username", "sunita")
    page.fill("#password", "wrong")
    page.click("#btn-login")
    page.wait_for_selector("#login-error:not(.hidden)")
    assert "Wrong username or password" in page.inner_text("#login-error")
    ctx.close()


def test_a_user_cannot_open_the_dashboard(browser, base):
    ctx = browser.new_context()
    log_in(ctx, base, "user")
    page = ctx.new_page()
    page.goto(base + "/")
    page.wait_for_url(base + "/pay")
    assert ctx.request.get(base + "/api/v1/kpis").status == 403
    ctx.close()


@pytest.mark.parametrize("role,home", [("user", "/pay"), ("merchant", "/merchant"), ("admin", "/")])
def test_a_judge_can_open_each_portal_with_one_click(browser, base, role, home):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(base + "/login")
    page.click(f"[data-role={role}]")
    page.wait_for_selector("#btn-test:visible")
    page.click("#btn-test")
    page.wait_for_url(base + home)
    ctx.close()


def test_a_new_person_can_sign_up_on_the_website(browser, base):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(base + "/login")
    page.click("#btn-switch")
    page.fill("#fullname", "Test Person")
    page.fill("#username", "e2e.person")
    page.fill("#password", "long-enough-pass")
    page.click("#btn-login")
    page.wait_for_url(base + "/pay")
    ctx.close()


def test_there_is_no_admin_sign_up_on_the_website(browser, base):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(base + "/login")
    page.click("[data-role=admin]")
    assert page.locator("#btn-switch").is_hidden()
    assert "cannot be created" in page.inner_text("#switch-text")
    ctx.close()



def _qr_file(tmp_path, text):
    import segno
    path = tmp_path / "qr.png"
    segno.make(text, error="m").save(path, kind="png", scale=8, border=4)
    return str(path)


def test_a_scanned_photo_is_checked_step_by_step_before_any_payment(phone, base, problems, tmp_path):
    open_phone(phone, base)
    phone.set_input_files("#scan-file", _qr_file(tmp_path, "upi://pay?pa=refund.helpdesk@simbank&pn=Refund&am=2999&tn=Scan%20to%20receive%20refund"))
    phone.wait_for_selector("#stages")
    assert phone.locator(".stage-bar[role=progressbar]").count() == 1
    phone.wait_for_selector("#verdict")
    assert phone.locator("#verdict").get_attribute("data-action") != "ALLOW"
    assert not problems, problems


def test_a_qr_without_an_amount_asks_for_one_and_other_codes_are_refused(phone, base, problems, tmp_path):
    open_phone(phone, base)
    phone.set_input_files("#scan-file", _qr_file(tmp_path, "upi://pay?pa=someone@simbank"))
    phone.wait_for_selector("#qr-amount")
    phone.fill("#qr-amount", "150")
    phone.click("#qr-go")
    phone.wait_for_selector("#verdict")
    open_phone(phone, base)
    phone.set_input_files("#scan-file", _qr_file(tmp_path, "just some words"))
    phone.wait_for_selector("#ready-error")
    assert "not a UPI" in phone.inner_text("#ready-error")
    assert not problems, problems


@pytest.mark.parametrize("position,sample", [(3, "ঀ"), (4, "ऀ"), (5, "஀"), (6, "ఀ")])
def test_a_decision_reads_in_each_language(phone, base, problems, position, sample):
    open_phone(phone, base)
    phone.click(f"#lang button:nth-child({position})")
    phone.click("[data-scenario=fake_collect]")
    phone.wait_for_selector("#verdict")
    low, high = ord(sample), ord(sample) + 127
    for selector in ("#verdict-title", "#reasons", "#btn-report"):
        assert any(low <= ord(ch) <= high for ch in phone.inner_text(selector)), selector
    phone.click("#lang button:nth-child(1)")
    assert not problems, problems


def test_the_feed_warns_and_an_admin_blocks(browser, base, problems):
    ctx = browser.new_context(viewport={"width": 390, "height": 800})
    page = ctx.new_page()
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(base + "/feed")
    page.wait_for_selector("#feed-login")
    log_in(ctx, base, "user")
    page.goto(base + "/feed")
    page.fill("#post-payee", "feed.scammer@simbank")
    page.fill("#post-body", "They said my KYC had expired and asked for a payment. Call 9876543210.")
    page.click("#post-go")
    post = page.locator(".feed-post").first
    post.wait_for()
    assert "9876543210" not in post.inner_text()
    post.locator(".vote").first.click()
    page.wait_for_selector(".vote.on")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    ctx.close()
    admin = browser.new_context()
    log_in(admin, base, "admin")
    page = admin.new_page()
    page.goto(base + "/feed")
    row = page.locator("#admin-panel .admin-row", has_text="feed.scammer@simbank").first
    row.locator("input").fill("Checked the reports")
    row.locator("button").click()
    page.locator("#admin-panel button", has_text="Unblock").first.wait_for()
    assert page.locator(".pill-block").count() >= 1
    admin.close()
    assert not problems, problems


def test_history_lists_filters_and_downloads(phone, base, problems):
    open_phone(phone, base)
    phone.click("[data-scenario=fake_collect]")
    phone.wait_for_selector("#verdict")
    phone.goto(base + "/history")
    phone.wait_for_selector("#hist-rows tbody tr")
    with phone.expect_download() as csv_file:
        phone.click("#export-csv")
    assert csv_file.value.suggested_filename == "satarkpay-history.csv"
    with phone.expect_download() as json_file:
        phone.click("#export-json")
    assert json_file.value.suggested_filename == "satarkpay-history.json"
    phone.fill("#hist-q", "no-such-thing-at-all")
    phone.wait_for_selector("#hist-empty")
    assert not problems, problems


def test_light_and_dark_can_be_chosen_on_the_website_and_are_remembered(phone, base, problems):
    open_phone(phone, base)
    colors = {}
    for _ in range(2):
        phone.click(".icon-btn")
        mode = phone.get_attribute("html", "data-theme")
        colors[mode] = phone.evaluate("getComputedStyle(document.body).backgroundColor")
    assert colors == {"dark": "rgb(0, 0, 0)", "light": "rgb(255, 255, 255)"}
    phone.goto(base + "/feed")
    assert phone.get_attribute("html", "data-theme") == mode
    assert not problems, problems


def test_light_and_dark_can_be_chosen_in_the_extension(browser):
    import functools
    import http.server
    import threading
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "extension"))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ctx = browser.new_context(color_scheme="light")
    page = ctx.new_page()
    page.add_init_script("""window.__store = {}; window.chrome = { runtime: { getManifest: () => ({ version: "1" }), sendMessage: () => {}, lastError: null, getURL: (p) => p },
      tabs: { query: (_q, cb) => cb([]), create: () => {} },
      storage: { onChanged: { addListener: () => {} }, local: { get: (k, cb) => cb(typeof k === "string" ? { [k]: window.__store[k] } : { ...k, ...window.__store }), set: (v, cb) => { Object.assign(window.__store, v); cb && cb(); } } } };""")
    page.goto(f"http://127.0.0.1:{server.server_address[1]}/popup.html")
    page.wait_for_function("document.getElementById('theme').textContent !== ''")
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(255, 255, 255)"
    page.click("#theme")
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(0, 0, 0)"
    assert page.evaluate("window.__store.theme") == "dark"
    ctx.close()
    server.shutdown()
