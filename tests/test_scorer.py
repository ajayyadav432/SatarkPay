"""The two models, the formula, the policy and the explanations."""
import json

import numpy as np
import pytest
import xgboost as xgb

from app import config
from app.payments import explain, policy
from app.payments.features import FEATURES, FeatureStore
from app.payments.models import Bands, FastForest, anomaly_matrix, anomaly_weight, ensemble, fuse
from app.payments.rules import combined_rule_weight, rule_hits
from app.payments.scorer import Scorer, level_for

T0 = 1_790_000_000.0
DAY = 86400.0


def pay(ts=T0, payer="sunita@simsbi", payee="kirana.om1@simhdfc", amount=180.0, kind="QR", device="d1", city=0, note="", link=None, balance=200000.0, txn_id="x"):
    return {"event": "txn", "txn_id": txn_id, "ts": ts, "payer": payer, "payee": payee, "amount": amount, "kind": kind,
            "device": device, "city": city, "note": note, "link": link, "balance": balance}


@pytest.fixture()
def scorer():
    directory = {"kirana.om1@simhdfc": {"created": T0 - 900 * DAY, "merchant": True, "verified": False}, "sunita@simsbi": {"created": T0 - 2000 * DAY, "merchant": False, "verified": False},
                 "refund-sbi@simybl": {"created": T0 - 2 * DAY, "merchant": True, "verified": False}, "electricity.board1@simhdfc": {"created": T0 - 2000 * DAY, "merchant": True, "verified": True},
                 "deepak.m1203@simaxis": {"created": T0 - 700 * DAY, "merchant": False, "verified": False}}
    s = Scorer(FeatureStore(directory))
    for i in range(12):     # a normal history: small daytime shop payments on one phone in one city
        s.observe(pay(ts=T0 - (12 - i) * DAY, amount=150.0 + 10 * i))
    return s


# --- the models --------------------------------------------------------------------------

def test_fast_forest_gives_exactly_what_scikit_learn_gives():
    m = ensemble()
    rng = np.random.default_rng(0)
    X = rng.normal(size=(300, len(m.bundle["anomaly_features"]))) * rng.uniform(0.1, 6, size=len(m.bundle["anomaly_features"]))
    theirs = m.forest.score_samples(X)
    ours = np.array([m.fast.score_one(row) for row in X])
    assert np.allclose(ours, theirs, atol=1e-9)
    assert isinstance(m.fast, FastForest)


def test_shap_adds_up_to_the_models_output_exactly(scorer):
    m = ensemble()
    f = scorer.store.features_for(pay(payee="refund-sbi@simybl", amount=2999, kind="COLLECT", note="Refund of Rs 2999 approve to receive"))
    x = np.array([f[n] for n in FEATURES], dtype=np.float32)
    values, base = m.shap_values(x)
    margin = m.booster.predict(xgb.DMatrix(x.reshape(1, -1), feature_names=FEATURES), output_margin=True)[0]
    assert base + values.sum() == pytest.approx(float(margin), abs=1e-3)
    assert 1 / (1 + np.exp(-(base + values.sum()))) == pytest.approx(m.probability(x), abs=1e-3)


def test_shap_matches_the_official_library(scorer):
    shap = pytest.importorskip("shap")
    m = ensemble()
    f = scorer.store.features_for(pay(payee="refund-sbi@simybl", amount=2999, kind="COLLECT"))
    x = np.array([f[n] for n in FEATURES], dtype=np.float32)
    ours, _ = m.shap_values(x)
    try:
        theirs = shap.TreeExplainer(m.booster).shap_values(x.reshape(1, -1))
    except Exception as exc:    # the library's support for a new XGBoost file format can lag behind
        pytest.skip(f"shap cannot read this model: {exc}")
    assert np.allclose(np.asarray(theirs)[0], ours, atol=1e-3)


def test_models_were_trained_without_future_or_labels_in_the_forest():
    bundle = json.loads(config.BUNDLE_FILE.read_text(encoding="utf-8"))
    assert bundle["features"] == FEATURES
    assert "label" not in bundle["anomaly_features"] and "note_risk" not in bundle["anomaly_features"]
    assert bundle["splits"]["train"][1] < bundle["splits"]["validation"][0] <= bundle["splits"]["validation"][1] < bundle["splits"]["test"][0]


# --- the formula -------------------------------------------------------------------------

def test_more_evidence_never_lowers_the_risk():
    assert fuse(0.2, 0.0, 0.0) == pytest.approx(0.2)
    last = 0.0
    for w in (0.0, 0.1, 0.3, 0.6, 0.9):
        now = float(fuse(0.2, w, 0.1))
        assert now >= last
        last = now
    assert fuse(1.0, 0.0, 0.0) == 1.0 and fuse(0.0, 0.0, 0.0) == 0.0


def test_the_score_rises_with_risk_and_levels_match_the_bands():
    b = Bands({"low": 0.01, "medium": 0.1, "high": 0.3, "critical": 0.8})
    risks = np.linspace(0, 1, 200)
    scores = b.score(risks)
    assert (np.diff(scores) >= 0).all() and scores[0] == 0 and scores[-1] == 100
    assert b.score(0.1) == 40 and b.score(0.3) == 60 and b.score(0.8) == 80
    assert [level_for(s) for s in (0, 25, 45, 65, 85)] == ["Safe", "Low", "Medium", "High", "Critical"]


def test_anomaly_weight_stays_within_limits():
    assert anomaly_weight(0.5) == 0 and anomaly_weight(0.99) == 0
    assert 0 < anomaly_weight(0.995) < anomaly_weight(0.999) <= 0.15 and anomaly_weight(1.0) == pytest.approx(0.15)


def test_missing_values_are_filled_for_the_forest():
    m = ensemble()
    x = np.full((1, len(FEATURES)), np.nan)
    assert not np.isnan(anomaly_matrix(x, m.medians)).any()


# --- hard rules ---------------------------------------------------------------------------

def _hits(**kw):
    base = dict(kind_collect=0, is_merchant=0, verified=0, receive_lure=0, vpa_risk=0, reports=0, sms_mention_risk=0, link_risk=0, link_official=0, payee_known=1)
    return {n for n, _ in rule_hits(**{**base, **kw})}


def test_a_person_to_person_collect_is_a_plain_fact():
    assert "p2p_collect" in _hits(kind_collect=1)
    assert "p2p_collect" not in _hits(kind_collect=1, is_merchant=1)
    assert "p2p_collect" not in _hits(kind_collect=1, payee_known=0), "we cannot call an unknown ID a person"


def test_rules_do_not_punish_verified_or_official_payees():
    assert "receive_lure" not in _hits(receive_lure=1, verified=1)
    assert "scam_link" not in _hits(link_risk=80, link_official=1)
    assert "scam_link" in _hits(link_risk=80)
    assert "scam_sms_link" not in _hits(sms_mention_risk=70, link_official=1), "a bill reminder, then paying on the real site"
    assert "scam_sms_link" in _hits(sms_mention_risk=70)
    assert "scam_sms_link" not in _hits(sms_mention_risk=30)


def test_one_complaint_is_not_a_rule_and_three_are():
    """One or two complaints reach 1.9% of genuine payments, at 5% precision (measured). The model still sees them."""
    assert not _hits(reports=2)
    assert "reported_many" in _hits(reports=3)
    assert combined_rule_weight([("a", 0.5), ("b", 0.5)]) == pytest.approx(0.75)


# --- the policy: the most questioned logic ---------------------------------------------------

RANK = {a: i for i, a in enumerate(policy.ACTIONS)}


@pytest.mark.parametrize("amount", [30.0, 199.0, 200.0, 5000.0, 100000.0])
@pytest.mark.parametrize("layers", [0, 1, 2, 3])
@pytest.mark.parametrize("fact", [False, True])
def test_higher_risk_never_gives_a_softer_action(amount, layers, fact):
    actions = [policy.decide_action(s, amount, layers, fact) for s in range(0, 101)]
    assert all(RANK[a] <= RANK[b] for a, b in zip(actions, actions[1:])), actions


@pytest.mark.parametrize("score", range(0, 101, 5))
def test_a_model_alone_can_never_refuse_a_payment(score):
    for layers in (0, 1):
        assert policy.decide_action(score, 100000.0, layers, False) != policy.BLOCK


def test_two_layers_or_a_plain_fact_can_refuse():
    assert policy.decide_action(90, 5000.0, 2, False) == policy.BLOCK
    assert policy.decide_action(90, 5000.0, 1, True) == policy.BLOCK


def test_low_scores_go_through_and_a_small_amount_is_only_warned():
    assert policy.decide_action(39, 100000.0, 3, True) == policy.ALLOW
    assert policy.decide_action(70, 50.0, 1, False) == policy.WARN
    assert policy.decide_action(70, 5000.0, 1, False) == policy.HOLD


def test_counting_layers():
    assert policy.layers_agreeing(0.9, 0.5, 0.0) == 1
    assert policy.layers_agreeing(0.9, 0.999, 0.0) == 2
    assert policy.layers_agreeing(0.9, 0.999, 0.7) == 3
    assert policy.layers_agreeing(0.1, 0.5, 0.1) == 0


# --- whole payments ----------------------------------------------------------------------------

def test_the_score_shown_is_the_score_the_policy_used(scorer):
    for amount in (900, 5000, 9000, 20000, 45000, 90000):
        r = scorer.score(pay(ts=T0 + 3600, payee="new.person.acct@simybl", amount=amount, kind="PAY", note="rent"))
        assert (r["action"] == "ALLOW") == (r["score"] < policy.WARN_FROM), r


def test_a_normal_payment_goes_through_quietly(scorer):
    r = scorer.score(pay(ts=T0 + 3600 * 3, amount=210))
    assert r["action"] == policy.ALLOW and not r["alert"] and r["reasons"] == []


def test_a_fake_refund_request_is_stopped_and_says_why(scorer):
    r = scorer.score(pay(ts=T0 + 60, payee="refund-sbi@simybl", amount=2999, kind="COLLECT", note="Refund of Rs 2999 approve to receive"))
    assert r["stopped"] and r["level"] in ("High", "Critical")
    text = " ".join(x["text_en"] for x in r["reasons"])
    assert "never receives" in text and "Refund of Rs 2999" in text, text
    assert r["likely"] == "fake_collect"


def test_a_person_to_person_collect_is_refused_because_upi_stopped_it(scorer):
    r = scorer.score(pay(ts=T0 + 60, payee="deepak.m1203@simaxis", amount=1500, kind="COLLECT", note="please send"))
    assert r["action"] == policy.BLOCK
    assert any("1 October 2025" in x["text_en"] for x in r["reasons"])


def test_a_real_bill_with_the_same_alarming_word_is_not_punished(scorer):
    """SatarkAI alone gives 'electricity bill oct' Medium 40. Paid to a verified biller it must pass."""
    r = scorer.score(pay(ts=T0 + 3 * 3600, payee="electricity.board1@simhdfc", amount=900, kind="PAY", note="electricity bill oct"))
    assert r["action"] == policy.ALLOW, r["model"]


def test_every_reason_is_in_english_and_hindi(scorer):
    r = scorer.score(pay(ts=T0 + 60, payee="refund-sbi@simybl", amount=45000, kind="COLLECT", device="d9", city=3, note="Refund of Rs 45000 approve to receive"))
    assert r["reasons"]
    for reason in r["reasons"]:
        assert reason["text_en"] and reason["text_hi"]
        assert any("ऀ" <= ch <= "ॿ" for ch in reason["text_hi"]), reason
    for line in r["advice"]:
        assert line["text_en"] and any("ऀ" <= ch <= "ॿ" for ch in line["text_hi"])
    assert any("ऀ" <= ch <= "ॿ" for ch in r["headline_hi"])


def test_reasons_quote_this_payments_real_numbers(scorer):
    r = scorer.score(pay(ts=T0 + 60, payee="amit.v2291@simpnb", amount=80000, kind="PAY", note="RBI safe account"), explain_always=True)
    text = " ".join(x["text_en"] for x in r["reasons"])
    assert "₹80,000" in text and "times your usual payment" in text, text
    assert "RBI safe account" in text, "the note is quoted as it was written"


def test_model_reasons_are_ordered_by_their_real_shap_weight(scorer):
    r = scorer.score(pay(ts=T0 + 60, payee="amit.v2291@simpnb", amount=80000, kind="PAY", note="RBI safe account"), explain_always=True)
    weights = [x["shap"] for x in r["reasons"] if x["source"] == "model"]
    assert weights == sorted(weights, reverse=True) and all(w >= explain.MIN_SHAP for w in weights)


def test_the_waterfall_adds_up_to_the_models_real_output(scorer):
    """Found in code review: features outside every group were dropped, so the 'exact' sum was not the model's output."""
    r = scorer.score(pay(ts=T0 + 60, payee="refund-sbi@simybl", amount=2999, kind="COLLECT"), explain_always=True)
    w = r["shap"]
    assert w["base"] + sum(i["shap"] for i in w["items"]) + w["rest"] == pytest.approx(w["output"], abs=0.02)
    p = r["model"]["xgb_probability"]
    assert w["output"] == pytest.approx(np.log(p / (1 - p)), abs=0.02)


def test_every_feature_belongs_to_a_reason_group():
    assert set(explain._FEATURE_GROUP) == set(FEATURES)


def test_scoring_does_not_record_anything(scorer):
    t = pay(ts=T0 + 60, payee="new.person1@simybl", amount=500, kind="PAY")
    a, b = scorer.score(t, explain_always=True), scorer.score(t, explain_always=True)
    assert a["score"] == b["score"]
    assert scorer.store.features_for(t)["new_payee"] == 1.0


def test_a_scam_note_can_never_inject_markup_into_a_reason_field_type(scorer):
    r = scorer.score(pay(ts=T0 + 60, payee="refund-sbi@simybl", amount=2999, kind="COLLECT", note="<img src=x onerror=alert(1)> approve to receive"))
    assert all(isinstance(x["text_en"], str) for x in r["reasons"])  # shown with textContent: see tests/test_e2e.py


def test_rupee_formatting_uses_indian_grouping():
    assert explain.rupees(999) == "₹999"
    assert explain.rupees(1000) == "₹1,000"
    assert explain.rupees(125000) == "₹1,25,000"
    assert explain.rupees(10000000) == "₹1,00,00,000"
