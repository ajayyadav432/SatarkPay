"""Attacks to launch from the dashboard, and ready-made payments for the phone screen. All of it is fictional."""
from __future__ import annotations

from ml.simulate import PERSONA_SHOP, PERSONAS

ATTACKS = {
    "fake_collect": {"title": "Fake collect request", "title_hi": "नकली collect request",
                     "detail": "A new merchant-style ID sends refund requests to many people at once. Since P2P collect ended, scammers need a merchant-style account."},
    "phishing_link": {"title": "Phishing SMS and link", "title_hi": "फ़िशिंग SMS और लिंक",
                      "detail": "A fake KYC SMS goes out. A few people open the link and pay on the fake page."},
    "mule_ring": {"title": "Mule ring", "title_hi": "मनी म्यूल गिरोह",
                  "detail": "Victims of a job scam pay a mule, who moves the money on within minutes. No note or link to read: only the money's behaviour gives it away."},
    "takeover": {"title": "SIM swap takeover", "title_hi": "SIM स्वैप से खाते पर कब्ज़ा",
                 "detail": "Someone else's phone, in another city, at night, emptying the account."},
    "coached": {"title": "\"Digital arrest\"", "title_hi": "\"डिजिटल अरेस्ट\"",
                "detail": "A frightened person sends large amounts from their own phone, at home, in daylight."},
}


def launch_attack(live, name: str) -> dict:
    """Puts the attack into the world's future, a moment from now. The stream reaches it within seconds."""
    w = live.world
    ts = live.clock + 60.0
    sunita = w.users[PERSONAS["sunita"]["vpa"]]
    if name == "fake_collect":
        victims = [w.users[v] for v in live.phones if v in w.users]
        return w.launch_fake_collect(ts, victims=victims, n=30, stealth=False, local="refund-sbi", amount=2999, note="Refund of Rs {a} approve to receive")
    if name == "phishing_link":     # always a few victims: an attack on stage must not depend on chance
        return w.launch_phishing(ts, victims=[w._victim(0.15) for _ in range(4)], recipients=60, stealth=False, brand="sbi")
    if name == "mule_ring":
        info = w.launch_mule_inflow(ts, n=14, stealth=False, entries=1, fast=True)
        live.last_mule = info["entry"]
        return info
    if name == "takeover":
        victim = w.users[PERSONAS["priya"]["vpa"]]
        w.balance[victim.vpa] = max(w.balance.get(victim.vpa, 0.0), PERSONAS["priya"]["balance"])     # launching it twice still finds money
        return w.launch_takeover(ts, victim=victim, stealth=False)
    if name == "coached":
        w.balance[sunita.vpa] = max(w.balance.get(sunita.vpa, 0.0), PERSONAS["sunita"]["balance"])
        return w.launch_coached(ts, victim=sunita, stealth=False, fast=True)
    raise ValueError(name)


# What the bank or network would know about the demo's fictional accounts: (is it a shop, days since it opened).
DEMO_ACCOUNTS = {"refund-sbi@simybl": (True, 3), "sbi.kyc.update@simybl": (True, 5), "olx.buyer.help77@simybl": (False, 20), "rohit.k7741@simybl": (False, 8),
                 "amit.v2291@simpnb": (False, 12), "deepak.m1203@simaxis": (False, 700)}


def phone_scenarios(live, persona: str) -> list[dict]:
    """Ready-made payments for the phone screen. The server scores them like any other payment."""
    me = PERSONAS[persona]
    acct = live.world.users[me["vpa"]]
    mule = getattr(live, "last_mule", None)
    for vpa, (shop, days) in DEMO_ACCOUNTS.items():
        live.world.directory.setdefault(vpa, {"created": live.clock - days * 86400.0, "merchant": shop, "verified": False, "category": "demo"})
    base = {"device": acct.device, "city": me["city"], "balance": round(live.world.balance.get(me["vpa"], 0.0), 2)}
    return [
        {"id": "shop", "title": "Pay the local shop", "title_hi": "दुकान पर भुगतान", "kind_label": "genuine", **base, "payee": PERSONA_SHOP, "amount": 180.0, "kind": "QR", "note": ""},
        {"id": "fake_collect", "title": "A \"refund\" request", "title_hi": "\"रिफंड\" का अनुरोध", "kind_label": "scam", **base, "payee": "refund-sbi@simybl", "amount": 2999.0, "kind": "COLLECT",
         "note": "Refund of Rs 2999 approve to receive"},
        {"id": "phishing", "title": "Pay from an SMS link", "title_hi": "SMS के लिंक से भुगतान", "kind_label": "scam", **base, "payee": "sbi.kyc.update@simybl", "amount": 499.0, "kind": "LINK", "note": "KYC fee",
         "link": "http://sbi-kyc-update.xyz/pay", "sms": "Dear customer, your SBI account will be blocked today. Update your KYC immediately: http://sbi-kyc-update.xyz/login", "sms_sender": "9876501234"},
        {"id": "qr", "title": "\"Scan to receive\"", "title_hi": "\"स्कैन करके पैसे पाएँ\"", "kind_label": "scam", **base, "payee": "olx.buyer.help77@simybl", "amount": 12000.0, "kind": "QR", "note": "scan to receive"},
        {"id": "mule", "title": "Pay a job \"deposit\"", "title_hi": "नौकरी की \"जमा राशि\"", "kind_label": "scam", **base, "payee": mule or "rohit.k7741@simybl", "amount": 25000.0, "kind": "PAY", "note": "joining fee"},
        {"id": "coached", "title": "\"Digital arrest\" transfer", "title_hi": "\"डिजिटल अरेस्ट\" ट्रांसफ़र", "kind_label": "scam", **base, "payee": "amit.v2291@simpnb", "amount": 80000.0, "kind": "PAY", "note": "RBI safe account"},
        {"id": "p2p_collect", "title": "A friend's collect request", "title_hi": "दोस्त का collect request", "kind_label": "scam", **base, "payee": "deepak.m1203@simaxis", "amount": 1500.0, "kind": "COLLECT", "note": "please send"},
    ]
