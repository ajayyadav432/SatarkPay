"""The feature store: hand-computed windows, no peeking at the future, and the context layer."""
import math

import pytest

from app.payments.context import link_signal, note_signal, sms_signal, vpa_signal
from app.payments.features import ANOMALY_FEATURES, FEATURES, FeatureStore, hour_of
from ml.simulate import World, WorldConfig

T0 = 1_790_000_000.0
HOUR = 3600.0
DAY = 86400.0


def pay(ts=T0, payer="a@sim", payee="b@sim", amount=100.0, kind="PAY", device="d1", city=0, note="", link=None, balance=None, txn_id="x"):
    return {"event": "txn", "txn_id": txn_id, "ts": ts, "payer": payer, "payee": payee, "amount": amount, "kind": kind,
            "device": device, "city": city, "note": note, "link": link, "balance": balance}


def seen(store, *txns):
    for t in txns:
        store.observe(t)


def test_the_engine_models_are_really_loaded():
    """The engine still answers without its models, only worse, and its own tests then skip. This must fail loudly."""
    from app.analysis import models
    assert all(models.status().values()), f"SatarkPay models not found in {models.config.MODELS_DIR}"
    assert link_signal("http://sbi-kyc-update.xyz/pay?pa=refund@ybl&am=2999")["score"] == 90, "the URL model did not run"


# --- nothing from the future -------------------------------------------------------

def test_a_payment_cannot_see_itself():
    s = FeatureStore()
    f = s.features_for(pay(amount=500))
    assert f["out_count_1h"] == 0 and f["out_sum_24h"] == 0 and f["payee_in_count_24h"] == 0
    assert f["new_payee"] == 1.0 and f["history_n"] == 0


def test_features_do_not_depend_on_later_events():
    s1, s2 = FeatureStore(), FeatureStore()
    first = pay(ts=T0, amount=100)
    target = pay(ts=T0 + 60, amount=900, payee="c@sim")
    later = pay(ts=T0 + 120, amount=5000, payee="c@sim")
    seen(s1, first)
    seen(s2, first)
    a = s1.features_for(target)
    s2.features_for(later)          # s2 looks at a later payment first, without recording it
    b = s2.features_for(target)
    for name in FEATURES:
        assert (a[name] == b[name]) or (math.isnan(a[name]) and math.isnan(b[name])), name


def test_a_later_event_only_shows_up_once_it_has_been_recorded():
    s = FeatureStore()
    seen(s, pay(ts=T0, payer="v1@sim", payee="m@sim", amount=1000))
    before = s.features_for(pay(ts=T0 + 10, payer="v2@sim", payee="m@sim"))
    seen(s, pay(ts=T0 + 5, payer="v3@sim", payee="m@sim", amount=1000))
    after = s.features_for(pay(ts=T0 + 10, payer="v2@sim", payee="m@sim"))
    assert before["payee_unique_in_24h"] == 1 and after["payee_unique_in_24h"] == 2


# --- hand-computed windows -----------------------------------------------------------

def test_velocity_windows():
    s = FeatureStore()
    seen(s, pay(ts=T0, amount=100), pay(ts=T0 + 30 * 60, amount=200), pay(ts=T0 + 5 * HOUR, amount=400))
    f = s.features_for(pay(ts=T0 + 5.5 * HOUR, amount=50))
    assert f["out_count_1h"] == 1 and f["out_sum_1h"] == 400
    assert f["out_count_24h"] == 3 and f["out_sum_24h"] == 700


def test_windows_forget_after_a_day():
    s = FeatureStore()
    seen(s, pay(ts=T0, amount=100))
    f = s.features_for(pay(ts=T0 + 25 * HOUR, amount=50))
    assert f["out_count_24h"] == 0 and f["out_sum_24h"] == 0
    assert f["new_payee"] == 0.0, "paying the same person again is still not new"


def test_amount_against_usual():
    s = FeatureStore()
    for i, a in enumerate([100, 200, 300]):
        seen(s, pay(ts=T0 + i * 3600, amount=a))
    f = s.features_for(pay(ts=T0 + 4 * HOUR, amount=4000))
    assert f["amt_vs_median"] == pytest.approx(20.0) and f["amt_vs_max"] == pytest.approx(4000 / 300)


def test_too_little_history_is_unknown_not_zero():
    s = FeatureStore()
    seen(s, pay(ts=T0, amount=100))
    f = s.features_for(pay(ts=T0 + 60, amount=4000))
    assert math.isnan(f["amt_vs_median"]) and math.isnan(f["hour_rarity"])


def test_new_device_and_jump_in_place():
    s = FeatureStore()
    seen(s, pay(ts=T0, device="d1", city=0))              # Jaipur
    same = s.features_for(pay(ts=T0 + HOUR, device="d1", city=0))
    assert same["new_device"] == 0.0 and same["km_from_last"] == 0.0
    moved = s.features_for(pay(ts=T0 + HOUR, device="d9", city=3))   # Bengaluru, an hour later
    assert moved["new_device"] == 1.0 and moved["km_from_last"] > 1500 and moved["kmph"] > 1500


def test_many_accounts_on_one_phone():
    s = FeatureStore()
    for i in range(4):
        seen(s, pay(ts=T0 + i, payer=f"m{i}@sim", device="shared"))
    assert s.features_for(pay(ts=T0 + 9, payer="m9@sim", device="shared"))["device_accounts"] == 5
    assert s.features_for(pay(ts=T0 + 9, payer="m0@sim", device="shared"))["device_accounts"] == 4


# --- mule signals ------------------------------------------------------------------

def test_fan_in_and_money_passing_through():
    s = FeatureStore()
    for i in range(5):
        seen(s, pay(ts=T0 + i, payer=f"v{i}@sim", payee="mule@sim", amount=1000))
    seen(s, pay(ts=T0 + 100, payer="mule@sim", payee="next@sim", amount=4500))
    as_payee = s.features_for(pay(ts=T0 + 200, payer="new@sim", payee="mule@sim", amount=1000))
    assert as_payee["payee_unique_in_24h"] == 5 and as_payee["payee_first_time_share"] == 1.0
    assert as_payee["payee_passthrough"] == pytest.approx(0.9)
    as_payer = s.features_for(pay(ts=T0 + 200, payer="mule@sim", payee="next@sim", amount=450))
    assert as_payer["payer_unique_in_24h"] == 5 and as_payer["forward_ratio"] == pytest.approx(450 / 5000)


def test_a_returning_customer_is_not_a_first_time_payer():
    s = FeatureStore()
    seen(s, pay(ts=T0, payer="regular@sim", payee="shop@sim"))
    seen(s, pay(ts=T0 + 2 * DAY, payer="regular@sim", payee="shop@sim"))
    f = s.features_for(pay(ts=T0 + 2 * DAY + 5, payer="other@sim", payee="shop@sim"))
    assert f["payee_first_time_share"] == 0.0


def test_collect_requests_declines_and_reports():
    s = FeatureStore()
    for i in range(4):
        req = pay(ts=T0 + i, payer=f"v{i}@sim", payee="scam@sim", amount=2999, kind="COLLECT", txn_id=f"c{i}")
        s.observe(req)
        s.observe({"event": "outcome", "ts": T0 + 10 + i, "txn_id": f"c{i}", "payer": f"v{i}@sim", "payee": "scam@sim", "amount": 2999, "approved": i == 0})
    s.observe({"event": "report", "ts": T0 + 20, "payee": "scam@sim"})
    f = s.features_for(pay(ts=T0 + 30, payer="v9@sim", payee="scam@sim", kind="COLLECT"))
    assert f["payee_collects_24h"] == 4 and f["payee_decline_share"] == pytest.approx(0.75)
    assert f["payee_reports_30d"] == 1 and f["payee_in_count_24h"] == 1, "only the approved request moved money"


def test_a_stopped_payment_moves_nothing():
    s = FeatureStore()
    s.observe(pay(ts=T0, payer="mule@sim", payee="next@sim", amount=4000), moved=False)
    f = s.features_for(pay(ts=T0 + 10, payer="x@sim", payee="next@sim"))
    assert f["payee_in_count_24h"] == 0
    assert s.features_for(pay(ts=T0 + 10, payer="mule@sim", payee="next@sim"))["new_payee"] == 1.0


def test_unknown_payee_is_unknown():
    s = FeatureStore({"a@sim": {"created": T0 - DAY, "merchant": False, "verified": False}})
    f = s.features_for(pay(payee="stranger@sim"))
    assert f["payee_known"] == 0.0 and math.isnan(f["payee_age_days"]) and f["payer_age_days"] == pytest.approx(1.0)


def test_payments_from_a_cold_start_have_no_crash():
    f = FeatureStore().features_for(pay(device=None, city=None, balance=None))
    assert math.isnan(f["new_device"]) and math.isnan(f["km_from_last"]) and math.isnan(f["amt_to_balance"])


def test_time_of_day_is_indian_time():
    assert hour_of(1_790_000_000.0 - 1_790_000_000.0 % 86400 - 19800) == 0


# --- context layer: gaps measured in the engine ------------------------------------

@pytest.mark.parametrize("note", ["Refund of Rs 2999 approve to receive", "Approve to get cashback Rs 750", "Enter UPI PIN to receive Rs 5000",
                                  "Aapka refund 1499 approve karein", "scan to receive money", "Scan karo paise milenge",
                                  "Accept to receive money", "रिफंड पाने के लिए स्वीकार करें"])
def test_notes_that_ask_you_to_act_to_receive_money_are_caught(note):
    s = note_signal(note)
    assert s["receive_lure"] and s["score"] >= 85 and s["evidence"]


@pytest.mark.parametrize("note", ["dinner", "rent", "kiraya", "trip share", "Order 48211", "electricity bill oct", "bijli bill", "chai", "medicine", ""])
def test_everyday_notes_are_not_receive_lures(note):
    assert not note_signal(note)["receive_lure"]


@pytest.mark.parametrize("note,lo", [("KYC update fee", 40), ("KBC prize claim fee", 40), ("joining fee", 30), ("security deposit", 30)])
def test_scam_words_and_fee_words_raise_the_score(note, lo):
    assert note_signal(note)["score"] >= lo


@pytest.mark.parametrize("vpa,lo", [("paytm.cashback.offer@okaxis", 80), ("sbi-kyc-refund@ybl", 80), ("refund-sbi@simybl", 80),
                                    ("customer.care.hdfc@simybl", 60), ("prize.kbc2026@simybl", 50), ("cashback.offer77@simybl", 50)])
def test_upi_ids_imitating_a_brand_or_using_scam_words(vpa, lo):
    assert vpa_signal(vpa)["score"] >= lo


@pytest.mark.parametrize("vpa", ["rahul.sharma98@okhdfcbank", "sunita.sharma@simsbi", "ramesh.kirana@simaxis", "shree.enterprises12@simybl", "kirana.amit22@simhdfc"])
def test_ordinary_upi_ids_are_not_flagged(vpa):
    assert vpa_signal(vpa)["score"] == 0


@pytest.mark.parametrize("vpa", ["payal.n1982@simpaytm", "payal.sharma@okaxis", "ramesh.kotak12@okaxis", "anita.kotak@ybl"])
def test_real_indian_names_are_not_mistaken_for_brands(vpa):
    """Found by checking which genuine accounts the first version accused: everyone named Payal looked like PayPal."""
    assert vpa_signal(vpa)["score"] == 0


@pytest.mark.parametrize("vpa,brand", [("paypa1.support@ybl", "PayPal"), ("kotak.kyc.update@ybl", "Kotak Mahindra Bank")])
def test_real_tricks_with_the_same_brands_are_still_caught(vpa, brand):
    assert vpa_signal(vpa)["brand"] == brand


def test_a_payment_gateway_link_says_nothing_either_way():
    """The engine alone gives paytm.me High 60, a false alarm on a real payment link."""
    for url in ("https://paytm.me/x7Ks-9f", "https://rzp.io/l/ab12cd"):
        s = link_signal(url)
        assert s["score"] == 0 and not s["official"]


def test_a_verified_merchant_is_exempt_from_the_name_check():
    directory = {"sbi.card@simsbi": {"created": T0 - 900 * DAY, "merchant": True, "verified": True}}
    assert FeatureStore(directory).features_for(pay(payee="sbi.card@simsbi"))["vpa_risk"] == 0
    assert FeatureStore().features_for(pay(payee="sbi.card@simsbi"))["vpa_risk"] > 0


def test_links_use_the_context_engine():
    assert link_signal("http://sbi-kyc-update.xyz/pay?pa=refund@ybl&am=2999")["score"] >= 80
    irctc = link_signal("https://www.irctc.co.in/nget/payment")
    assert irctc["score"] == 0 and irctc["official"]


def test_a_scam_sms_counts_for_15_minutes_and_a_mention_for_a_day():
    s = FeatureStore()
    text = "Dear customer, your SBI account will be blocked today. Update your KYC immediately: http://sbi-kyc-update.xyz/login"
    s.record_sms("a@sim", text, "9876501234", T0)
    soon = s.features_for(pay(ts=T0 + 120, link="http://sbi-kyc-update.xyz/pay", kind="LINK"))
    assert soon["sms_risk_15m"] >= 80 and soon["sms_mentions_payee"] >= 80
    assert s.recent_sms("a@sim", "b@sim", "sbi-kyc-update.xyz", T0 + 120)["minutes_ago"] == 2
    later = s.features_for(pay(ts=T0 + 3 * HOUR, link="http://sbi-kyc-update.xyz/pay", kind="LINK"))
    assert later["sms_risk_15m"] == 0.0 and later["sms_mentions_payee"] >= 80
    assert s.features_for(pay(ts=T0 + 120, payer="other@sim", kind="PAY"))["sms_risk_15m"] == 0.0


def test_an_sms_naming_the_upi_id_links_the_payment():
    s = FeatureStore()
    s.record_sms("a@sim", "URGENT: your account will be blocked today. Pay the KYC fee to refund-help@simybl immediately", "9876501234", T0)
    assert s.features_for(pay(ts=T0 + 60, payee="refund-help@simybl"))["sms_mentions_payee"] >= 40
    assert sms_signal("Hey are we still meeting for lunch tomorrow at 1?", "")["score"] < 20


# --- replay and shape ----------------------------------------------------------------

def test_an_old_harmless_mention_and_a_new_scam_do_not_add_up():
    """Found in code review: a harmless SMS naming a shop yesterday plus an unrelated scam today read as 'a scam SMS named this shop'."""
    from app.payments.rules import rule_hits_for
    s = FeatureStore()
    s.record_sms("a@sim", "Thanks for shopping at shop.om1@simybl. See you again!", "VM-SHOPOM", T0)
    s.record_sms("a@sim", "Dear customer, your SBI account will be blocked today. Update your KYC immediately: http://sbi-kyc-update.xyz/login", "9876501234", T0 + 20 * HOUR)
    f = s.features_for(pay(ts=T0 + 20 * HOUR + 300, payee="shop.om1@simybl"))
    assert f["sms_risk_15m"] >= 80, "the scam still counts as a recent scam"
    assert f["sms_mentions_payee"] < 40, "but the message naming this shop was harmless"
    assert "scam_sms_link" not in [r for r, _ in rule_hits_for(f)]


def test_every_feature_is_produced_and_anomaly_features_are_a_subset():
    assert set(FeatureStore().features_for(pay())) == set(FEATURES)
    assert set(ANOMALY_FEATURES) <= set(FEATURES)
    assert not {"note_risk", "link_risk", "vpa_risk"} & set(ANOMALY_FEATURES), "the anomaly model reads behaviour, not words"


def test_replaying_a_world_gives_identical_features_each_time():
    cfg = WorldConfig(seed=21, days=3, n_users=500, n_merchants=90)

    def replay():
        world, out = World(cfg), []
        store = FeatureStore(world.directory)
        while (ev := world.next_event()) is not None:
            if ev["event"] == "txn":
                out.append(store.features_for(ev))
            store.observe(ev)
            world.commit(ev)
        return out

    a, b = replay(), replay()
    assert len(a) == len(b) and len(a) > 500
    for x, y in zip(a[::50], b[::50]):
        for n in FEATURES:
            assert x[n] == y[n] or (math.isnan(x[n]) and math.isnan(y[n])), n
