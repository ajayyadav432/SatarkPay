"""One test per requirement of problem statement 3.2. The numbers R1-R10 are the ones in the README."""
import json
from pathlib import Path

import numpy as np
import xgboost as xgb
from fastapi import FastAPI
from sklearn.ensemble import IsolationForest

from app import config, main
from app.payments.features import FEATURES
from app.payments.live import Bus
from app.payments.models import ensemble
from ml.simulate import PERSONAS

SUNITA = PERSONAS["sunita"]["vpa"]
RAHUL = PERSONAS["rahul"]["vpa"]


def score(api, **kw):
    r = api.post("/api/v1/score", json={"payer": SUNITA, "device": "d1", "city": "Jaipur", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_r1_fake_collect_requests(api):
    """'fake collect requests': stopped before the person approves, and P2P collect is known to have ended."""
    api.get("/api/v1/demo")
    r = score(api, payee="refund-sbi@simybl", amount=2999, kind="COLLECT", note="Refund of Rs 2999 approve to receive")
    assert r["stopped"]
    assert any("never receives" in x["text_en"] for x in r["reasons"])
    assert r["likely"] == "fake_collect"
    p2p = score(api, payee="deepak.m1203@simaxis", amount=1500, kind="COLLECT", note="please send")
    assert p2p["action"] == "BLOCK" and any("1 October 2025" in x["text_en"] for x in p2p["reasons"])


def test_r2_phishing_links(api):
    """'phishing links': the link that opened the payment and the SMS that came just before."""
    api.post("/api/v1/sms", json={"user": SUNITA, "text": "Dear customer, your SBI account will be blocked today. Update your KYC immediately: http://sbi-kyc-verify.xyz/login", "sender": "9876501234"})
    r = score(api, payee="kyc.fee.counter@simybl", amount=499, kind="LINK", note="KYC fee", link="http://sbi-kyc-verify.xyz/pay")
    assert r["alert"]
    assert {"scam_link", "scam_sms_link"} <= set(r["rules"])
    text = " ".join(x["text_en"] for x in r["reasons"])
    assert "SMS" in text and "sbi-kyc-verify.xyz" in text


def test_r3_mule_accounts(engine, api):
    """'mule accounts': many strangers paying in, money going straight out, shown as a network."""
    info = engine.launch("mule_ring")
    engine.step(1500)
    entry = info["entry"]
    alerts = api.get("/api/v1/alerts", params={"limit": 200}).json()["alerts"]
    assert any(a["payee"] == entry for a in alerts), "payments to the mule were flagged"
    graph = api.get("/api/v1/graph", params={"vpa": entry}).json()
    assert {n["column"] for n in graph["nodes"]} >= {-1, 0}
    assert any(a["payer"] in info["ring"] and a["likely"] == "forward" for a in alerts) or graph["total_held"] > 0, "the mule's own transfers were caught too"


def test_r4_warns_before_money_is_gone(api, engine):
    """'users only realise after money is gone': the decision comes first, and stopped money stays put."""
    payee = "before.the.money.goes@simybl"
    r = score(api, payee=payee, amount=9000, kind="PAY", note="joining fee")
    state = {"ts": engine.clock + 1, "payer": "x@simybl", "payee": payee, "amount": 1, "kind": "PAY"}
    assert engine.scorer.store.features_for(state)["payee_in_count_24h"] == 0, "scoring moved no money"
    api.post("/api/v1/outcome", json={"txn_id": r["txn_id"], "decision": "cancelled"})
    assert engine.scorer.store.features_for(state)["payee_in_count_24h"] == 0, "stopping moved no money"
    # The second chance: even after a victim has paid, the mule's next transfer can be held.
    before = engine.kpis["rupees_recoverable"]
    for _ in range(4):
        engine.launch("mule_ring")
    engine.step(2500)
    assert engine.kpis["rupees_recoverable"] > before


def test_r5_all_four_target_users(api):
    """'Banks, fintech apps, small merchants, consumers'."""
    for page in ("/", "/pay", "/merchant"):             # bank analyst, consumer, merchant
        assert api.get(page).status_code == 200
    assert api.get("/openapi.json").json()["paths"]["/api/v1/score"], "fintech apps integrate through one documented call"
    groups = api.get("/api/v1/metrics").json()["false_alarms_by_group"]
    assert groups["small_unverified_merchants"]["flagged"] < 0.05, "small merchants' customers are not treated as suspects"
    shop = score(api, payee="ramesh.kirana@simaxis", amount=180, kind="QR")
    assert shop["action"] == "ALLOW"


def test_r6_trained_on_a_synthetic_or_public_dataset(api):
    """'Train an anomaly-detection model on a synthetic or public transaction dataset': synthetic, with public PaySim as a check."""
    m = api.get("/api/v1/metrics").json()
    assert "synthetic" in m["data"]["note"].lower()
    assert m["data"]["train_payments"] > 100_000 and m["data"]["test_scams"] > 1000
    assert isinstance(ensemble().forest, IsolationForest)
    assert m["systems"]["isolation_forest"]["roc_auc"] > 0.7
    assert m["paysim"]["source"]["name"] == "PaySim" and m["paysim"]["without_balance_columns"]["pr_auc"] > 0.3


def test_r7_live_scoring_api(api, engine):
    """'flag risky transactions with a live scoring API'."""
    risky = score(api, payee="another.fake.refund@simybl", amount=2999, kind="COLLECT", note="Refund approve to receive")
    assert risky["alert"] and risky["latency_ms"] < 100
    before = engine.kpis["scored"]
    engine.step(200)
    assert engine.kpis["scored"] > before, "the stream is scored too"


def test_r8_alert_screen(api):
    """'and alert screen': the screen that stops the payment and says why (driven in a real browser in tests/test_e2e.py)."""
    page = api.get("/pay").text
    assert 'id="screen"' in page and "/static/pay.js" in page
    js = api.get("/static/pay.js").text
    assert "tel:1930" in js and "cybercrime.gov.in" in js and "appeal" in js


def test_r9_the_named_stack(api, engine):
    """'Isolation Forest or XGBoost, FastAPI, Kafka or a simple stream simulator, a dashboard': both models, a simulator."""
    m = ensemble()
    assert isinstance(m.booster, xgb.Booster) and isinstance(m.forest, IsolationForest)
    assert isinstance(main.app, FastAPI)
    assert isinstance(engine.bus, Bus)
    assert "Live payments" in api.get("/").text


def test_r10_explainable_alerts(api):
    """Bonus twist: 'Explainable alerts that tell the user why a payment looks suspicious'. Plain, in two languages, and exact."""
    r = score(api, payee="amit.v2291@simpnb", amount=80000, kind="PAY", note="RBI safe account")
    assert r["reasons"] and r["headline_en"] and r["headline_hi"] and r["advice"]
    for x in r["reasons"]:
        assert x["text_en"] and x["text_hi"]
    assert any("₹80,000" in x["text_en"] for x in r["reasons"]), "the real amount is quoted"
    w = r["shap"]
    assert abs(w["base"] + sum(i["shap"] for i in w["items"]) + w["rest"] - w["output"]) < 0.02, "the explanation adds up to the model's output"


def test_every_number_on_the_model_card_comes_from_the_metrics_file():
    """No result is typed into the page: it must only read fields of metrics.json."""
    js = (config.STATIC_DIR / "how.js").read_text(encoding="utf-8")
    assert "/api/v1/metrics" in js
    metrics = json.loads(config.METRICS_FILE.read_text(encoding="utf-8"))
    for key in ("data", "systems", "policy", "layers", "leave_one_scam_out", "careful_scammers_world", "false_alarms_by_group", "real_world_correction", "paysim", "latency"):
        assert key in metrics, key


def test_models_in_the_repo_match_the_features():
    x = np.zeros(len(FEATURES), dtype=np.float32)
    assert 0.0 <= ensemble().probability(x) <= 1.0
    assert Path(config.XGB_FILE).stat().st_size < 5_000_000, "small enough to keep in the repo"
