"""The REST API, the live engine, the reused sensors' contracts and security."""
import json
import time

import pytest

from app import config
from app.payments import store
from ml.simulate import PERSONAS

SUNITA = PERSONAS["sunita"]["vpa"]


def body(**kw):
    return {"payer": SUNITA, "payee": "refund-sbi@simybl", "amount": 2999, "kind": "COLLECT", "note": "Refund of Rs 2999 approve to receive", "device": "d1", "city": "Jaipur", **kw}


# --- scoring ------------------------------------------------------------------------------

def test_score_returns_the_decision_and_reasons(api):
    r = api.post("/api/v1/score", json=body())
    assert r.status_code == 200
    d = r.json()
    assert d["action"] in ("WARN", "HOLD", "BLOCK") and d["txn_id"] and d["reasons"] and d["latency_ms"] < 200
    assert set(d["model"]) >= {"xgb_probability", "anomaly_percentile", "rule_weight", "risk", "layers_agreeing"}
    assert d["shap"]["items"]


@pytest.mark.parametrize("bad", [{"amount": 0}, {"amount": -5}, {"payer": "not a upi id"}, {"payee": "x"}, {"kind": "WIRE"}, {"note": "x" * 201}, {"link": "x" * 3000}, {"surprise": 1}])
def test_bad_input_is_refused(api, bad):
    assert api.post("/api/v1/score", json=body(**bad)).status_code == 422


def test_upi_ids_are_normalised(api):
    r = api.post("/api/v1/score", json=body(payer=" Sunita.Sharma@SIMSBI ", payee=" Refund-SBI@simybl "))
    assert r.status_code == 200


def test_unknown_city_is_not_an_error(api):
    assert api.post("/api/v1/score", json=body(city="Atlantis")).status_code == 200


def test_outcome_only_works_once(api):
    txn = api.post("/api/v1/score", json=body()).json()["txn_id"]
    assert api.post("/api/v1/outcome", json={"txn_id": txn, "decision": "cancelled"}).status_code == 200
    assert api.post("/api/v1/outcome", json={"txn_id": txn, "decision": "paid"}).status_code == 404


def test_nothing_moves_until_the_person_decides(api, engine):
    payee = "brand.new.person1@simybl"
    before = engine.scorer.store.features_for({"ts": engine.clock + 1, "payer": "x@simybl", "payee": payee, "amount": 10, "kind": "PAY"})["payee_in_count_24h"]
    txn = api.post("/api/v1/score", json=body(payee=payee, kind="PAY", note="", amount=500)).json()["txn_id"]
    during = engine.scorer.store.features_for({"ts": engine.clock + 1, "payer": "x@simybl", "payee": payee, "amount": 10, "kind": "PAY"})["payee_in_count_24h"]
    assert before == during == 0
    api.post("/api/v1/outcome", json={"txn_id": txn, "decision": "paid"})
    after = engine.scorer.store.features_for({"ts": engine.clock + 1, "payer": "x@simybl", "payee": payee, "amount": 10, "kind": "PAY"})["payee_in_count_24h"]
    assert after == 1


def test_one_report_protects_the_next_person(api, engine):
    """The report loop: three people report an account and the next payment to it is stopped harder."""
    payee = "lucky.helpdesk9@simybl"
    first = api.post("/api/v1/score", json=body(payee=payee, kind="PAY", note="", amount=4000)).json()
    for who in (p["vpa"] for p in PERSONAS.values()):
        t = api.post("/api/v1/score", json=body(payer=who, payee=payee, kind="PAY", note="", amount=4000)).json()["txn_id"]
        assert api.post("/api/v1/outcome", json={"txn_id": t, "decision": "reported"}).status_code == 200
    next_person = api.post("/api/v1/score", json=body(payer=PERSONAS["rahul"]["vpa"], payee=payee, kind="PAY", note="", amount=4000)).json()
    assert engine.reports_of(payee) == 3
    assert next_person["score"] > first["score"]
    assert "reported_many" in next_person["rules"]
    assert any("reported" in r["text_en"] for r in next_person["reasons"])


def test_sms_context_raises_the_payment_that_follows(api):
    plain = api.post("/api/v1/score", json=body(payee="sbi.kyc.update1@simybl", kind="LINK", note="", amount=499, link="http://sbi-kyc-update.xyz/pay")).json()
    sms = api.post("/api/v1/sms", json={"user": SUNITA, "text": "Dear customer, your SBI account will be blocked today. Update your KYC immediately: http://sbi-kyc-update.xyz/login", "sender": "9876501234"})
    assert sms.status_code == 200 and sms.json()["level"] == "Critical"
    after = api.post("/api/v1/score", json=body(payee="sbi.kyc.update1@simybl", kind="LINK", note="", amount=499, link="http://sbi-kyc-update.xyz/pay")).json()
    assert after["score"] >= plain["score"]
    assert "scam_sms_link" in after["rules"]
    assert any("SMS" in r["text_en"] for r in after["reasons"])


# --- found in the security review -------------------------------------------------------------------

def test_a_hostname_is_refused_so_dns_rebinding_cannot_reach_the_app(api):
    assert api.post("/api/v1/sim/stop", headers={"Host": "rebind.attacker.example:8000", "Origin": "http://rebind.attacker.example:8000"}).status_code == 403
    assert api.get("/", headers={"Host": "rebind.attacker.example"}).status_code == 403
    for host in ("localhost:8000", "127.0.0.1:8000", "192.168.1.20:8000", "[::1]:8000"):
        assert api.get("/api/health", headers={"Host": host}).status_code == 200, host


def test_another_device_cannot_plant_an_sms_for_someone_else():
    msg = {"user": SUNITA, "text": "Your account will be blocked", "sender": "9"}
    assert _other_device("/api/v1/sms", json=msg).status_code == 401
    assert _other_device("/api/v1/sms", json=msg, headers={"X-Satark-Token": "test-pairing-code"}).status_code == 200


def test_an_sms_sent_with_a_payment_counts_for_that_payment_only(api):
    sms = "Dear customer, your AXIS account will be blocked today. Update your KYC immediately: http://axisbank-kyc-verify.top/login"
    pay = body(payer=PERSONAS["priya"]["vpa"], payee="one.off.sms@simybl", kind="LINK", note="", amount=499, link="http://axisbank-kyc-verify.top/pay")
    assert "scam_sms_link" in api.post("/api/v1/score", json={**pay, "sms": sms, "sms_sender": "9000000002"}).json()["rules"]
    assert "scam_sms_link" not in api.post("/api/v1/score", json=pay).json()["rules"]


def test_only_the_token_holder_can_answer_for_a_payment(api, engine):
    r = api.post("/api/v1/score", json=body(payee="token.check@simybl", kind="PAY", note="", amount=500)).json()
    assert r["token"]
    assert api.post("/api/v1/outcome", json={"txn_id": r["txn_id"], "token": "guess", "decision": "cancelled"}).status_code == 404
    assert api.post("/api/v1/outcome", json={"txn_id": r["txn_id"], "token": r["token"], "decision": "cancelled"}).status_code == 200


def test_a_client_cannot_choose_a_payment_number(api):
    assert api.post("/api/v1/score", json=body(txn_id="P-1")).status_code == 422


def test_one_person_reporting_many_times_counts_once(api, engine):
    payee = "report.once@simybl"
    for _ in range(3):
        t = api.post("/api/v1/score", json=body(payee=payee, kind="PAY", note="", amount=100)).json()["txn_id"]
        api.post("/api/v1/outcome", json={"txn_id": t, "decision": "reported"})
    assert engine.reports_of(payee) == 1


def test_a_backslash_cannot_disguise_a_link_as_official(api):
    from app.payments.context import link_signal
    assert not link_signal("https://evil.com\\@sbi.co.in/")["official"]
    assert api.get("/api/check-url", params={"u": "https://evil.com\\@sbi.co.in/"}).json()["trusted"] is False


# --- the server enforces the decision, not the button ---------------------------------------------

def _scored(api, engine, action, **kw):
    """A payment whose decision is fixed, so that the rule itself is what gets tested."""
    r = api.post("/api/v1/score", json=body(payee=f"decided.{action.lower()}{engine.kpis['scored']}@simybl", kind="PAY", note="", amount=4000, **kw)).json()
    engine.pending[r["txn_id"]]["result"] = {**engine.pending[r["txn_id"]]["result"], "action": action, "stopped": action in ("HOLD", "BLOCK")}
    return r["txn_id"]


def test_a_blocked_payment_cannot_be_paid_by_calling_the_api(api, engine):
    """Found in code review: BLOCK was enforced only by hiding the button on the phone."""
    t = _scored(api, engine, "BLOCK")
    r = api.post("/api/v1/outcome", json={"txn_id": t, "decision": "paid"})
    assert r.status_code == 409 and "blocked" in r.json()["detail"]
    assert api.post("/api/v1/outcome", json={"txn_id": t, "decision": "cancelled"}).status_code == 200, "it can still be cancelled"


def test_the_pause_is_enforced_by_the_server(api, engine):
    engine.pauses = {"WARN": 60, "HOLD": 60}
    try:
        t = _scored(api, engine, "HOLD")
        r = api.post("/api/v1/outcome", json={"txn_id": t, "decision": "paid"})
        assert r.status_code == 409 and "wait" in r.json()["detail"]
        engine.pending[t]["scored_at"] -= 61
        assert api.post("/api/v1/outcome", json={"txn_id": t, "decision": "paid"}).status_code == 200
    finally:
        engine.pauses = {}


def test_record_true_lets_an_app_record_without_waiting(api, engine):
    engine.pauses = {"WARN": 60, "HOLD": 60}
    try:
        assert api.post("/api/v1/score", json=body(kind="PAY", note="", payee="ramesh.kirana@simaxis", amount=180, record=True)).status_code == 200
    finally:
        engine.pauses = {}


# --- where the money really went ------------------------------------------------------------------

def test_paying_anyway_on_a_hold_counts_as_lost_not_stopped(engine):
    """Found in code review: the hero number counted a held payment as stopped even after the person paid it."""
    engine.scorer.store.directory.setdefault("hold.me@simybl", {"created": engine.clock - 86400, "merchant": False, "verified": False})
    entry = engine.score_request({"payer": SUNITA, "payee": "hold.me@simybl", "amount": 5000.0, "kind": "PAY", "label": 1, "typology": "mule_inflow"})
    engine.pending[entry["txn"]["txn_id"]]["result"] = {**entry["result"], "action": "HOLD", "stopped": True}
    stopped, lost = engine.kpis["rupees_stopped"], engine.kpis["rupees_lost"]
    engine.decide(entry["txn"]["txn_id"], "paid")
    assert engine.kpis["rupees_stopped"] == stopped and engine.kpis["rupees_lost"] == lost + 5000.0


def test_a_collect_request_moves_no_money_until_it_is_approved(engine):
    """Found in code review: every request not stopped counted as lost, even the many that people declined."""
    lost = engine.kpis["rupees_lost"]
    txn = {"event": "txn", "txn_id": "C-pending-1", "ts": engine.clock + 1, "payer": PERSONAS["priya"]["vpa"], "payee": "ramesh.kirana@simaxis", "amount": 700.0, "kind": "COLLECT",
           "device": "d", "city": 3, "note": "Order 1", "link": None, "label": 1, "typology": "fake_collect", "balance": None}
    engine.handle(txn)
    assert engine.feed[-1]["status"] in ("pending", "stopped")
    assert engine.kpis["rupees_lost"] == lost, "asking is not taking"
    if engine.feed[-1]["status"] == "pending":
        engine.handle({"event": "outcome", "ts": engine.clock + 1, "txn_id": "C-pending-1", "payer": txn["payer"], "payee": txn["payee"], "amount": 700.0, "approved": False, "label": 1, "typology": "fake_collect"})
        assert engine.kpis["rupees_lost"] == lost, "declined"
        engine.handle({"event": "outcome", "ts": engine.clock + 1, "txn_id": "C-pending-1", "payer": txn["payer"], "payee": txn["payee"], "amount": 700.0, "approved": True, "label": 1, "typology": "fake_collect"})
        assert engine.kpis["rupees_lost"] == lost + 700.0, "approved"


def test_feed_rows_say_whether_money_really_arrived(api, engine):
    person = engine.world.user_list[200]    # someone no other test has been paying from
    usual = {"payer": person.vpa, "payee": person.shops[0].vpa, "kind": "QR", "note": "", "amount": 120, "device": person.device, "city": person.city}
    r = api.post("/api/v1/score", json=body(**usual)).json()
    assert r["action"] == "ALLOW", r["model"]
    api.post("/api/v1/outcome", json={"txn_id": r["txn_id"], "decision": "cancelled"})
    assert engine.feed[-1]["txn_id"] == r["txn_id"] and engine.feed[-1]["status"] == "cancelled", "the shop must not see this as received"
    t = api.post("/api/v1/score", json=body(**usual)).json()["txn_id"]
    api.post("/api/v1/outcome", json={"txn_id": t, "decision": "paid"})
    assert engine.feed[-1]["status"] == "moved"


# --- the stream stays alive ------------------------------------------------------------------------

def test_one_bad_event_does_not_end_the_stream(engine, monkeypatch):
    """Found in code review: any error ended the thread for good while the screen still said Live."""
    import threading
    from app.payments.live import Live
    calls = []

    def flaky(self, count=1):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        self._stop.set()

    monkeypatch.setattr(Live, "step", flaky)
    errors, was_running = engine.stream_errors, engine.running
    engine.running = True
    engine._stop.clear()    # the test client's shutdown leaves it set
    try:
        t = threading.Thread(target=engine._loop)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive() and len(calls) == 2, "it carried on after the error"
        assert engine.stream_errors == errors + 1 and engine.snapshot()["stream_errors"] == errors + 1
    finally:
        engine._stop.clear()
        engine.running = was_running


def test_the_graph_can_be_read_while_the_stream_writes():
    """Found in code review: without a lock the dashboard's read could fail while the stream was writing."""
    import threading
    from app.payments.graph import MoneyGraph
    g = MoneyGraph()
    g.add_suspect("mule@sim")
    stop = threading.Event()
    failures = []

    def writer():
        i = 0
        while not stop.is_set():
            i += 1
            g.record(f"v{i % 3000}@sim", "mule@sim", 10.0, "moved", float(i))

    w = threading.Thread(target=writer)
    w.start()
    try:
        for _ in range(300):
            try:
                g.around("mule@sim")
            except RuntimeError as exc:
                failures.append(exc)
    finally:
        stop.set()
        w.join()
    assert not failures


# --- the stream and attacks ---------------------------------------------------------------------

def test_stepping_the_stream_scores_payments(engine):
    before = engine.kpis["scored"]
    engine.step(300)
    assert engine.kpis["scored"] > before
    snap = engine.snapshot()
    assert snap["clock_label"].startswith("Day ") and snap["latency_ms"]["p50"] is not None


def test_every_attack_launches_and_gets_detected(engine, api):
    """Each must produce payments every time: an attack showing 0 payments on stage would be a failed demo."""
    from app.payments.scenarios import ATTACKS
    for name in ATTACKS:
        assert api.post(f"/api/v1/sim/attack/{name}").status_code == 200
    assert api.post("/api/v1/sim/attack/nope").status_code == 404
    engine.step(2500)
    snap = engine.snapshot()
    attacks = {a["name"]: a for a in snap["attacks"]}
    assert set(attacks) >= set(ATTACKS)
    for name, a in attacks.items():
        assert a["events"] > 0, f"{name} produced no payments"
    assert sum(a["flagged"] for a in attacks.values()) > 0


def test_a_held_mule_transfer_keeps_money_recoverable(engine):
    """The second chance: money caught at the mule's next hop can still go back."""
    before = engine.kpis["rupees_recoverable"]
    for _ in range(4):
        engine.launch("mule_ring")
    engine.step(2500)
    assert engine.kpis["rupees_recoverable"] > before


def test_the_graph_shows_the_ring_from_what_was_observed(engine, api):
    info = engine.launch("mule_ring")
    engine.step(1500)
    g = api.get("/api/v1/graph", params={"vpa": info["entry"]}).json()
    assert g["focus"] == info["entry"]
    columns = {n["column"] for n in g["nodes"]}
    assert -1 in columns, "the people who paid this account are shown"
    assert 0 in columns


def test_a_scam_request_reaches_the_open_phone_and_waits_for_the_person(engine):
    ch = engine.subscribe_phone(SUNITA)
    try:
        engine.launch("fake_collect")
        engine.step(400)
        items = ch.drain()
        incoming = [i for i in items if i["type"] == "incoming"]
        assert incoming, "the request never reached the phone"
        txn_id = incoming[0]["txn"]["txn_id"]
        assert incoming[0]["result"]["reasons"]
        assert engine.decide(txn_id, "reported")["moved"] is False
    finally:
        engine.unsubscribe(ch, SUNITA)


def test_the_join_qr_code_is_a_complete_svg_file(api, monkeypatch):
    """An <img> shows nothing for an SVG without its XML namespace. Found by looking at the screen: the endpoint said 200."""
    from app import main
    monkeypatch.setattr(main, "_lan_address", lambda: "http://192.168.1.20:8000")
    r = api.get("/api/v1/join.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert b'xmlns="http://www.w3.org/2000/svg"' in r.content
    assert api.get("/api/v1/join").json()["pay_url"] == "http://192.168.1.20:8000/pay"


def test_stream_endpoint_is_server_sent_events(engine):
    """Reads the generator directly: a test client would wait for a stream that never ends."""
    import asyncio

    from app.main import _events

    class FakeRequest:
        n = 0

        async def is_disconnected(self):
            self.n += 1
            return self.n > 2

    ch = engine.subscribe_dashboard()
    engine.step(50)

    async def collect():
        return [m async for m in _events(FakeRequest(), ch, engine)]

    messages = asyncio.run(collect())
    assert messages[0].startswith("data: ") and json.loads(messages[0][6:])["type"] == "hello"
    assert any(json.loads(m[6:]).get("items") for m in messages[1:])


def test_speed_only_accepts_known_values(api):
    assert api.post("/api/v1/sim/speed", json={"tps": 50}).json()["tps"] == 50
    assert api.post("/api/v1/sim/speed", json={"tps": 7}).status_code == 422


# --- alerts and the analyst -------------------------------------------------------------------------

def test_alerts_are_stored_and_a_confirmed_scam_counts_as_a_report(api, engine):
    payee = "fresh.scam.acct1@simybl"
    t = api.post("/api/v1/score", json=body(payee=payee)).json()["txn_id"]
    api.post("/api/v1/outcome", json={"txn_id": t, "decision": "cancelled"})
    alerts = api.get("/api/v1/alerts").json()["alerts"]
    mine = [a for a in alerts if a["payee"] == payee]
    assert mine
    alert = mine[0]
    assert api.get(f"/api/v1/alerts/{alert['id']}").json()["reasons"]
    assert engine.reports_of(payee) == 0
    updated = api.patch(f"/api/v1/alerts/{alert['id']}", json={"status": "confirmed_fraud"}).json()
    assert updated["status"] == "confirmed_fraud" and updated["reports"] == 1
    api.patch(f"/api/v1/alerts/{alert['id']}", json={"status": "confirmed_fraud"})
    assert engine.reports_of(payee) == 1, "confirming twice is one report"
    assert api.get("/api/v1/alerts", params={"status": "confirmed_fraud"}).json()["labelled"]["confirmed_fraud"] >= 1


def test_false_alarm_label_is_kept_for_retraining(api):
    t = api.post("/api/v1/score", json=body(payee="honest.shop.owner1@simybl")).json()["txn_id"]
    api.post("/api/v1/outcome", json={"txn_id": t, "decision": "cancelled"})
    alert = [a for a in api.get("/api/v1/alerts").json()["alerts"] if a["payee"] == "honest.shop.owner1@simybl"][0]
    assert api.patch(f"/api/v1/alerts/{alert['id']}", json={"status": "false_alarm"}).json()["status"] == "false_alarm"
    assert store.get_alert(alert["id"])["status"] == "false_alarm"


@pytest.mark.skipif(store.is_shared(), reason="a shared database is never cleared on start, because many copies use it")
def test_restarting_keeps_analyst_labels_and_never_overwrites_them(api):
    """Found in code review: payment numbers repeat after a restart, and the old code replaced the labelled alert."""
    base = {"ts": 1.0, "payer": "a@sim", "payee": "b@sim", "amount": 1.0, "score": 90, "level": "Critical", "action": "BLOCK", "source": "stream", "txn_id": "T2026-500"}
    first = store.save_alert(dict(base))
    store.set_status(first, "confirmed_fraud")
    second = store.save_alert(dict(base))
    assert second != first and store.get_alert(first)["status"] == "confirmed_fraud" and store.get_alert(second)["status"] == "new"
    store.init()    # a restart
    assert store.get_alert(first)["status"] == "confirmed_fraud", "decisions are kept for the next training"
    assert store.get_alert(second) is None, "alerts nobody looked at belong to the old run"


def test_unknown_alert_is_404(api):
    assert api.get("/api/v1/alerts/99999999").status_code == 404
    assert api.patch("/api/v1/alerts/99999999", json={"status": "false_alarm"}).status_code == 404


# --- pages and the demo -------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/pay", "/merchant", "/how", "/go"])
def test_pages_open_with_a_strict_content_policy(api, path):
    r = api.get(path)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert r.headers["x-content-type-options"] == "nosniff"


def test_demo_lists_people_and_payments(api):
    d = api.get("/api/v1/demo", params={"persona": "sunita"}).json()
    assert d["me"]["vpa"] == SUNITA and d["me"]["history"] >= 3
    assert {s["id"] for s in d["scenarios"]} >= {"shop", "fake_collect", "phishing", "qr", "mule", "coached", "p2p_collect"}
    assert api.get("/api/v1/demo", params={"persona": "mallory"}).status_code == 422


def test_the_demos_scam_payments_are_flagged_and_the_shop_is_not(api):
    d = api.get("/api/v1/demo", params={"persona": "sunita"}).json()
    results = {}
    for s in d["scenarios"]:
        if s.get("sms"):
            api.post("/api/v1/sms", json={"user": SUNITA, "text": s["sms"], "sender": s["sms_sender"]})
        fields = {k: s[k] for k in ("payee", "amount", "kind", "device", "city", "note", "balance") if s.get(k) is not None}
        if s.get("link"):
            fields["link"] = s["link"]
        results[s["id"]] = api.post("/api/v1/score", json={"payer": SUNITA, **fields}).json()
    assert results["shop"]["action"] == "ALLOW", results["shop"]["model"]
    for name in ("fake_collect", "phishing", "qr", "mule", "coached", "p2p_collect"):
        assert results[name]["action"] != "ALLOW", (name, results[name]["model"])
        assert results[name]["reasons"], name


# --- the reused Android app and extension: exact contracts ------------------------------------------------

def test_health_as_the_phone_app_expects(api):
    assert api.get("/api/health").json()["status"] == "ok"


def test_ingest_answers_what_the_phone_app_reads(api):
    r = api.post("/api/ingest", json={"text": "Dear customer, your SBI account will be blocked today. Update your KYC immediately: http://sbi-kyc-update.xyz/login",
                                      "channel": "sms", "sender": "9876501234", "source": "sms-app", "ref": "9876501234-1-99"})
    assert r.status_code == 200
    d = r.json()
    assert d["level"] == "Critical" and d["score"] >= 80 and d["reasons"] and d["category"] and d["history_raised"] is False and d["block"] is None
    again = api.post("/api/ingest", json={"text": "x", "channel": "sms", "sender": "9", "source": "sms-app", "ref": "9876501234-1-99"}).json()
    assert again["duplicate"] is True and again["level"] == "Critical"


def test_a_real_sms_through_the_phone_app_affects_the_next_payment(api):
    api.post("/api/ingest", json={"text": "Dear customer, your HDFC account will be blocked today. Update your KYC immediately: http://hdfc-kyc-update.top/login",
                                  "channel": "sms", "sender": "9000000001", "source": "sms-app", "ref": "real-sms-1"})
    r = api.post("/api/v1/score", json=body(payee="hdfc.fee.help@simybl", kind="LINK", note="", amount=999, link="http://hdfc-kyc-update.top/pay")).json()
    assert "scam_sms_link" in r["rules"]


def test_check_urls_as_the_extension_expects(api):
    d = api.post("/api/check-urls", json={"urls": ["http://sbi-kyc-update.xyz/login", "https://www.irctc.co.in/nget", "javascript:alert(1)"]}).json()["results"]
    assert d["http://sbi-kyc-update.xyz/login"]["needs_warning"] is True and d["https://www.irctc.co.in/nget"]["needs_warning"] is False
    assert "javascript:alert(1)" not in d


def test_check_url_as_the_extension_and_warning_page_expect(api):
    d = api.get("/api/check-url", params={"u": "http://sbi-kyc-update.xyz/login"}).json()
    assert d["needs_warning"] is True and d["factors"] and d["display"] and "level" in d
    assert api.get("/api/check-url", params={"u": "ftp://example.com/file"}).status_code == 400


# --- security ---------------------------------------------------------------------------------------------------

def _other_device(path, method="post", **kw):
    """A request as if from a judge's phone on the Wi-Fi, not from the laptop."""
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app, base_url="http://192.168.1.20:8000", client=("192.168.1.50", 5000)) as c:
        return getattr(c, method)(path, **kw)


@pytest.mark.parametrize("path", ["/api/v1/sim/start", "/api/v1/sim/stop", "/api/v1/sim/attack/fake_collect", "/api/v1/score"])
def test_without_a_login_nothing_runs(path):
    assert _other_device(path).status_code in (401, 422)


def test_without_a_login_alerts_cannot_be_labelled():
    assert _other_device("/api/v1/alerts/1", method="patch", json={"status": "false_alarm"}).status_code == 401


def test_other_devices_need_the_pairing_code_for_sms():
    msg = {"text": "hello", "channel": "sms", "sender": "9", "source": "sms-app"}
    assert _other_device("/api/ingest", json=msg).status_code == 401
    assert _other_device("/api/ingest", json=msg, headers={"X-Satark-Token": "wrong"}).status_code == 401
    assert _other_device("/api/ingest", json=msg, headers={"X-Satark-Token": "test-pairing-code"}).status_code == 200


def test_another_website_cannot_drive_the_app(api):
    r = api.post("/api/v1/sim/stop", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert api.post("/api/check-urls", json={"urls": ["http://a.com"]}, headers={"Origin": "chrome-extension://abcdef"}).status_code == 200


def test_metrics_are_served_from_the_file(api):
    m = api.get("/api/v1/metrics").json()
    assert m == json.loads(config.METRICS_FILE.read_text(encoding="utf-8"))
    assert "synthetic" in m["data"]["note"]


def test_the_score_stays_fast_under_a_burst(api):
    lat = []
    for i in range(50):
        t0 = time.perf_counter()
        api.post("/api/v1/score", json=body(payee=f"burst.acct{i}@simybl", kind="PAY", note="", amount=500 + i))
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    assert lat[int(len(lat) * 0.95)] < 100, lat[-5:]


# --- test QR codes for the phone app -----------------------------------------------------

@pytest.mark.parametrize("name", ["shop", "qr", "fake_collect", "mule", "phishing"])
def test_demo_qr_codes_are_served(api, name):
    r = api.get(f"/api/v1/demo/qr/{name}.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg")


def test_an_unknown_demo_qr_is_refused(api):
    assert api.get("/api/v1/demo/qr/nope.svg").status_code == 422


def test_a_demo_upi_qr_holds_a_simulated_id_and_the_scam_note(api):
    from urllib.parse import parse_qs, urlparse

    from app import main
    text = main._demo_qr_text(main.get_live(), "qr")
    assert text.startswith("upi://pay?")
    q = parse_qs(urlparse(text).query)
    assert q["pa"][0].split("@")[1].startswith("sim") and q["tn"] == ["scan to receive"] and float(q["am"][0]) > 0


def test_a_scanned_real_id_is_accepted_and_a_scam_note_still_stops_it(api):
    r = api.post("/api/v1/score", json=body(payee="someone.new@oksbi", amount=5000, kind="QR", note="scan to receive"))
    assert r.status_code == 200 and r.json()["stopped"]
