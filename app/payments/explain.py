"""Why a payment looks suspicious, in plain English and Hindi.

Reasons are not guessed afterwards. XGBoost's exact TreeSHAP values are added up per reason group, the groups are
ranked by that real weight, and each sentence is filled with the real numbers of this payment. Hard rules and the
SatarkPay engine add their own reasons. No language model is involved, so nothing can be invented.
"""
from __future__ import annotations

import math
import re

from app.payments.features import FEATURE_INDEX
from app.payments.geo import city_name

# Features that tell one story are explained together. A group's weight is the sum of its features' SHAP values.
GROUPS = {
    "amount_unusual": ["amount", "amt_vs_median", "amt_vs_max"],
    "drains_balance": ["amt_to_balance"],
    "new_payee": ["new_payee", "new_payees_1h"],
    "burst": ["out_count_1h", "out_count_24h", "out_sum_1h", "out_sum_24h"],
    "odd_hour": ["hour_rarity", "is_night"],
    "new_device": ["new_device", "device_age_h"],
    "shared_device": ["device_accounts"],
    "jump": ["km_from_last", "kmph"],
    "forwarding": ["forward_ratio", "payer_in_sum_24h", "payer_in_count_24h", "payer_unique_in_24h", "payer_first_time_share"],
    "young_payee": ["payee_age_days", "payee_known"],
    "unverified": ["payee_verified", "payee_is_merchant"],
    "fan_in": ["payee_unique_in_24h", "payee_in_count_24h", "payee_first_time_share", "payee_in_sum_24h"],
    "pass_through": ["payee_passthrough", "payee_out_sum_24h"],
    "collect_blast": ["payee_collects_24h", "payee_decline_share"],
    "reports": ["payee_reports_30d"],
    "note": ["note_risk", "receive_lure"],
    "link": ["link_risk", "link_official", "kind_link"],
    "fake_vpa": ["vpa_risk"],
    "sms": ["sms_risk_15m", "sms_mentions_payee"],
    "kind": ["kind_collect", "kind_qr", "kind_pay"],
    "history": ["history_n", "payer_age_days"],     # no sentence of its own, but it must count: SHAP only adds up with every feature
}
_FEATURE_GROUP = {f: g for g, fs in GROUPS.items() for f in fs}
MIN_SHAP = 0.15      # smaller pushes are not worth a person's attention
MAX_REASONS = 5


def rupees(x: float) -> str:
    """Indian digit grouping: 1,25,000."""
    n = int(round(x))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return "₹" + s


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def _usual(t: dict, f: dict) -> str | None:
    if _ok(f["amt_vs_median"]) and f["amount"] and f["amt_vs_median"] > 0:
        return rupees(f["amount"] / f["amt_vs_median"])
    return None


def _sentence(group: str, t: dict, f: dict, ctx: dict) -> tuple[str, str] | None:
    """English and Hindi for one reason, or None when this payment's values do not support saying it."""
    amount = rupees(f["amount"])
    if group == "amount_unusual" and _ok(f["amt_vs_median"]) and f["amt_vs_median"] >= 3:
        times, usual = round(f["amt_vs_median"]), _usual(t, f)
        return (f"{amount} is {times} times your usual payment of {usual}", f"{amount} आपके आम भुगतान {usual} से {times} गुना ज़्यादा है")
    if group == "drains_balance" and _ok(f["amt_to_balance"]) and f["amt_to_balance"] >= 0.4:
        share = min(100, round(f["amt_to_balance"] * 100))
        return (f"This would take {share}% of your balance", f"इससे आपके बैलेंस का {share}% चला जाएगा")
    if group == "new_payee" and f["new_payee"]:
        return (f"You have never paid {t['payee']} before", f"आपने {t['payee']} को पहले कभी भुगतान नहीं किया है")
    if group == "burst" and f["out_count_1h"] >= 2:
        n = int(f["out_count_1h"])
        return (f"{n} payments from this account in the last hour, {rupees(f['out_sum_1h'])} in total",
                f"पिछले एक घंटे में इस खाते से {n} भुगतान, कुल {rupees(f['out_sum_1h'])}")
    if group == "odd_hour" and f["is_night"]:
        return ("This is at an hour when you rarely pay", "आप इस समय आमतौर पर भुगतान नहीं करते")
    if group == "new_device" and f["new_device"] == 1:
        return ("This payment comes from a phone you have not used before", "यह भुगतान ऐसे फ़ोन से हो रहा है जिसे आपने पहले इस्तेमाल नहीं किया")
    if group == "shared_device" and f["device_accounts"] >= 3:
        n = int(f["device_accounts"])
        return (f"{n} different UPI accounts have been used on this phone", f"इस फ़ोन पर {n} अलग-अलग UPI खाते इस्तेमाल हुए हैं")
    if group == "jump" and _ok(f["km_from_last"]) and f["km_from_last"] >= 200:
        km = round(f["km_from_last"])
        return (f"Your last payment was {km:,} km from here, in {city_name(ctx.get('last_city'))}", f"आपका पिछला भुगतान यहाँ से {km:,} किमी दूर, {city_name(ctx.get('last_city'))} में था")
    if group == "forwarding" and _ok(f["forward_ratio"]) and f["payer_in_count_24h"] >= 1 and f["forward_ratio"] >= 0.5:
        share = min(100, round(f["forward_ratio"] * 100))
        n = int(f["payer_unique_in_24h"])
        return (f"This account received {rupees(f['payer_in_sum_24h'])} from {n} {'person' if n == 1 else 'people'} in 24 hours and is now sending {share}% of it out",
                f"इस खाते में 24 घंटे में {'1 व्यक्ति' if n == 1 else f'{n} लोगों'} से {rupees(f['payer_in_sum_24h'])} आए और अब इसका {share}% बाहर भेजा जा रहा है")
    if group == "young_payee" and _ok(f["payee_age_days"]) and f["payee_age_days"] < 60:
        days = max(1, round(f["payee_age_days"]))
        return (f"This account is only {days} day{'s' if days != 1 else ''} old", f"यह खाता सिर्फ़ {days} दिन पुराना है")
    if group == "young_payee" and not f["payee_known"]:
        return ("Nothing is known about this UPI ID", "इस UPI ID के बारे में कोई जानकारी नहीं है")
    if group == "unverified" and f["payee_is_merchant"] and not f["payee_verified"]:
        return ("This is not a verified merchant", "यह सत्यापित व्यापारी नहीं है")
    if group == "fan_in" and f["payee_unique_in_24h"] >= 5:
        n = int(f["payee_unique_in_24h"])
        return (f"{n} different people paid this account in the last 24 hours", f"पिछले 24 घंटों में {n} अलग-अलग लोगों ने इस खाते में पैसे भेजे")
    if group == "pass_through" and _ok(f["payee_passthrough"]) and f["payee_passthrough"] >= 0.5 and f["payee_in_count_24h"] >= 2:
        share = min(100, round(f["payee_passthrough"] * 100))
        return (f"{share}% of the money this account received has already left it, which is typical of mule accounts",
                f"इस खाते में आए पैसे का {share}% तुरंत बाहर चला गया, जो मनी म्यूल खातों में आम है")
    if group == "collect_blast" and f["payee_collects_24h"] >= 5:
        n = int(f["payee_collects_24h"])
        if _ok(f["payee_decline_share"]):
            share = round(f["payee_decline_share"] * 100)
            return (f"{n} people got a request from this account today, and {share}% of those who answered declined it",
                    f"आज {n} लोगों को इस खाते से अनुरोध मिला, और जवाब देने वालों में से {share}% ने मना कर दिया")
        return (f"{n} people got a request from this account today", f"आज {n} लोगों को इस खाते से अनुरोध मिला")
    if group == "reports" and f["payee_reports_30d"] >= 1:
        n = int(f["payee_reports_30d"])
        return (f"{n} {'person has' if n == 1 else 'people have'} reported this account", f"{'1 व्यक्ति' if n == 1 else f'{n} लोगों'} ने इस खाते की शिकायत की है")
    if group == "note" and f["note_risk"] >= 30:
        return _note_sentence(t, ctx)
    if group == "link" and f["kind_link"] and not f["link_official"]:
        domain = ctx.get("link", {}).get("domain") or "an unknown site"
        return (f"This payment was opened from a link on {domain}, which is not an official site", f"यह भुगतान {domain} के लिंक से खुला, जो कोई आधिकारिक साइट नहीं है")
    if group == "fake_vpa" and f["vpa_risk"] >= 50:
        sig = ctx.get("vpa", {})
        if sig.get("brand"):
            return (f"This UPI ID uses the name of {sig['brand']}, but it is not their account", f"यह UPI ID {sig['brand']} का नाम इस्तेमाल करती है, लेकिन यह उनका खाता नहीं है")
        return (f"This UPI ID uses scam words such as \"{sig.get('words', ['refund'])[0]}\"", f"इस UPI ID में \"{sig.get('words', ['refund'])[0]}\" जैसे धोखाधड़ी वाले शब्द हैं")
    if group == "sms" and (f["sms_mentions_payee"] >= 40 or f["sms_risk_15m"] >= 40):
        sms = ctx.get("sms") or {}
        mins = sms.get("minutes_ago", 0)
        if mins == 0:
            when, when_hi = "just now", "अभी"
        elif mins < 90:
            when, when_hi = f"{mins} minute{'s' if mins != 1 else ''} ago", f"{mins} मिनट पहले"
        else:
            hours = round(mins / 60)
            when, when_hi = f"{hours} hours ago", f"{hours} घंटे पहले"
        if f["sms_mentions_payee"] >= 40:
            return (f"You got a suspicious SMS {when} that points to this payment", f"आपको {when_hi} एक संदिग्ध SMS मिला जो इसी भुगतान की ओर इशारा करता है")
        return (f"You got a suspicious SMS {when}", f"आपको {when_hi} एक संदिग्ध SMS मिला")
    return None


def _note_sentence(t: dict, ctx: dict) -> tuple[str, str]:
    note = (t.get("note") or "").strip()[:80]
    sig = ctx.get("note", {})
    if sig.get("receive_lure"):
        return (f"The note says \"{note}\". Entering your PIN always sends money, it never receives it",
                f"नोट में लिखा है \"{note}\"। PIN डालने से पैसे हमेशा जाते हैं, कभी आते नहीं")
    return (f"The note says \"{note}\", which is common in scams", f"नोट में लिखा है \"{note}\", जो धोखाधड़ी में आम है")


# Hard rules are facts, so they always appear, whatever the SHAP values say.
RULE_REASONS = {
    "p2p_collect": ("A person asked you for money with a collect request. UPI stopped allowing this on 1 October 2025",
                    "किसी व्यक्ति ने collect request से पैसे माँगे। UPI ने यह सुविधा 1 अक्टूबर 2025 से बंद कर दी है"),
}
# Which rules are already told by a reason group, so that they are not said twice.
RULE_GROUP = {"receive_lure": "note", "scam_sms_link": "sms", "scam_link": "link", "reported_many": "reports", "fake_vpa": "fake_vpa"}

LIKELY = [
    ("p2p_collect", "Fake collect request", "नकली collect request"),
    ("fake_collect", "Fake collect request", "नकली collect request"),
    ("phishing", "Phishing link payment", "फ़िशिंग लिंक से भुगतान"),
    ("qr", "\"Scan to receive\" QR scam", "\"स्कैन करके पैसे पाएँ\" QR धोखाधड़ी"),
    ("forward", "Mule account moving money on", "मनी म्यूल खाता पैसे आगे भेज रहा है"),
    ("takeover", "Someone else may be using your account", "हो सकता है कोई और आपका खाता चला रहा हो"),
    ("mule", "Payment to a likely mule account", "संभावित मनी म्यूल खाते में भुगतान"),
    ("coached", "Pressure scam, such as a \"digital arrest\"", "दबाव वाली धोखाधड़ी, जैसे \"डिजिटल अरेस्ट\""),
    ("unusual", "Unusual payment", "असामान्य भुगतान"),
]
_LIKELY = {k: (en, hi) for k, en, hi in LIKELY}

ADVICE = {
    "fake_collect": [("Decline this request. To receive money you never approve anything or enter a PIN.", "इस अनुरोध को मना करें। पैसे पाने के लिए कभी कुछ स्वीकार नहीं करना होता, न ही PIN डालना होता है।")],
    "phishing": [("Do not pay on this page. Open your bank's official app instead.", "इस पेज पर भुगतान न करें। अपने बैंक का आधिकारिक ऐप खोलें।")],
    "qr": [("Do not scan. Scanning a QR code only ever sends money.", "स्कैन न करें। QR कोड स्कैन करने से सिर्फ़ पैसे जाते हैं।")],
    "takeover": [("Call your bank now and block UPI on this account.", "अभी अपने बैंक को कॉल करें और इस खाते पर UPI बंद कराएँ।")],
    "coached": [("No police or government agency asks for money over a call. Hang up and talk to someone you trust.", "पुलिस या कोई सरकारी एजेंसी फ़ोन पर पैसे नहीं माँगती। फ़ोन काटें और किसी भरोसेमंद व्यक्ति से बात करें।")],
    "forward": [("This looks like a mule account. The transfer is held so the money can still be recovered.", "यह मनी म्यूल खाता लगता है। यह ट्रांसफ़र रोका गया है ताकि पैसे वापस मिल सकें।")],
    "mule": [("Do not send money to someone you do not know, however good the offer sounds.", "जिसे आप नहीं जानते उसे पैसे न भेजें, चाहे ऑफ़र कितना भी अच्छा लगे।")],
    "unusual": [("Check with the person or shop on a number you already have before paying.", "भुगतान से पहले उस व्यक्ति या दुकान से अपने पास मौजूद नंबर पर पुष्टि करें।")],
}
LOST_MONEY = ("Lost money? Call 1930 at once, or report on cybercrime.gov.in.", "पैसे चले गए? तुरंत 1930 पर कॉल करें, या cybercrime.gov.in पर शिकायत करें।")


_PRESSURE_NOTE = re.compile(r"\b(?:safe\s+account|rbi|digital\s+arrest|legal|court|police|customs)\b", re.I)


def likely_type(t: dict, f: dict, rules: list[tuple[str, float]], group_weights: dict[str, float]) -> str:
    """A best guess at the kind of scam, from what actually drove this score. Checked against the labels in ml/evaluate.py."""
    names = {r for r, _ in rules}
    if "p2p_collect" in names or f["kind_collect"]:
        return "fake_collect"
    if f["kind_link"] and (f["link_risk"] >= 40 or f["sms_mentions_payee"] >= 40 or f["sms_risk_15m"] >= 40 or not f["link_official"]):
        return "phishing"
    # A takeover is a burst: only its first payment is on a brand-new phone, the next ones on a phone first seen minutes ago.
    fresh_phone = f["new_device"] == 1 or (_ok(f["device_age_h"]) and f["device_age_h"] < 12 and f["history_n"] >= 5)
    if fresh_phone or (_ok(f["km_from_last"]) and f["km_from_last"] >= 200 and group_weights.get("jump", 0) > 0):
        return "takeover"
    if _ok(f["forward_ratio"]) and f["forward_ratio"] >= 0.25 and f["payer_in_count_24h"] >= 1 and group_weights.get("forwarding", 0) > 0:
        return "forward"
    if f["kind_qr"] and (f["new_payee"] or f["note_risk"] >= 30):
        return "qr"
    if _PRESSURE_NOTE.search(t.get("note") or ""):
        return "coached"
    if _ok(f["amt_to_balance"]) and f["amt_to_balance"] >= 0.3 and f["amount"] >= 2000 and f["new_payee"] and not f["payee_is_merchant"]:
        return "coached"
    young = _ok(f["payee_age_days"]) and f["payee_age_days"] < 60
    many_strangers = _ok(f["payee_first_time_share"]) and f["payee_first_time_share"] >= 0.5
    if not f["payee_is_merchant"] and (f["new_payee"] or young or many_strangers):
        return "mule"
    return "unusual"


def group_shap(shap_values, names=None) -> dict[str, float]:
    """SHAP values added up per reason group. Log-odds; positive means more suspicious."""
    out: dict[str, float] = {}
    for feature, i in FEATURE_INDEX.items():
        g = _FEATURE_GROUP.get(feature)
        if g:
            out[g] = out.get(g, 0.0) + float(shap_values[i])
    return out


def build_reasons(t: dict, f: dict, shap_values, rules: list[tuple[str, float]], anomaly_pct: float, ctx: dict, normal: dict) -> tuple[list[dict], dict]:
    """Reasons ordered by what really drove the decision. Returns (reasons, group weights)."""
    weights = group_shap(shap_values)
    reasons: list[dict] = []
    said: set[str] = set()

    for rule, weight in sorted(rules, key=lambda r: -r[1]):
        if rule == "p2p_collect":
            en, hi = RULE_REASONS["p2p_collect"]
            reasons.append({"id": rule, "source": "rule", "text_en": en, "text_hi": hi, "weight": weight})
        else:
            group = RULE_GROUP.get(rule)
            if group and group not in said:
                said.add(group)
                s = _sentence(group, t, f, ctx)
                if s:
                    reasons.append({"id": group, "source": "rule", "text_en": s[0], "text_hi": s[1], "weight": weight})

    for group, value in sorted(weights.items(), key=lambda kv: -kv[1]):
        if value < MIN_SHAP or group in said or len(reasons) >= MAX_REASONS:
            continue
        s = _sentence(group, t, f, ctx)
        if s:
            said.add(group)
            reasons.append({"id": group, "source": "model", "text_en": s[0], "text_hi": s[1], "shap": round(value, 3)})

    if anomaly_pct >= 0.99 and len(reasons) < MAX_REASONS:
        s = _unusual_sentence(f, normal, anomaly_pct, said)
        reasons.append({"id": "anomaly", "source": "anomaly", "text_en": s[0], "text_hi": s[1], "percentile": round(anomaly_pct, 5)})
    return reasons, weights


# Complete sentences, so that the English and the Hindi both read naturally. Each names the reason group it would repeat.
_UNUSUAL = [("payee_unique_in_24h", "fan_in", "More people paid this account today than for 99% of normal payments", "इस खाते में आज 99% सामान्य भुगतानों से ज़्यादा लोगों ने पैसे भेजे"),
            ("forward_ratio", "forwarding", "More of the incoming money is being sent straight on than in 99% of normal payments", "आए हुए पैसे का 99% सामान्य भुगतानों से बड़ा हिस्सा तुरंत आगे भेजा जा रहा है"),
            ("kmph", "jump", "Your location changed faster than in 99% of normal payments", "आपकी जगह 99% सामान्य भुगतानों से ज़्यादा तेज़ी से बदली"),
            ("amt_vs_median", "amount_unusual", "Compared with your usual payment, this is bigger than 99% of normal payments", "आपके आम भुगतान की तुलना में यह 99% सामान्य भुगतानों से बड़ा है"),
            ("out_count_1h", "burst", "More payments in the last hour than in 99% of normal cases", "पिछले एक घंटे में 99% सामान्य मामलों से ज़्यादा भुगतान"),
            ("device_accounts", "shared_device", "More accounts on this phone than in 99% of normal cases", "इस फ़ोन पर 99% सामान्य मामलों से ज़्यादा खाते")]


def _unusual_sentence(f: dict, normal: dict, pct: float, said: set[str]) -> tuple[str, str]:
    """Describes the payment, not the forest: which value is furthest beyond what normal payments do."""
    for name, group, en, hi in _UNUSUAL:
        r = normal.get(name)
        if group not in said and r and _ok(f.get(name)) and f[name] > r["p99"] > 0:
            return en, hi
    top_pct = min(99.99, round(pct * 100, 2))
    return (f"Overall, this payment is more unusual than {top_pct}% of normal payments", f"कुल मिलाकर यह भुगतान {top_pct}% सामान्य भुगतानों से ज़्यादा असामान्य है")


def waterfall(shap_values, base: float, limit: int = 10) -> dict:
    """The full model explanation for the analyst: base value + contributions = the model's output."""
    groups = group_shap(shap_values)
    items = sorted(groups.items(), key=lambda kv: -abs(kv[1]))
    shown = [{"group": g, "shap": round(v, 3)} for g, v in items[:limit]]
    rest = sum(v for _, v in items[limit:])
    return {"base": round(base, 3), "items": shown, "rest": round(rest, 3), "output": round(base + sum(v for _, v in items), 3)}


def headline(action: str, likely: str) -> tuple[str, str]:
    en, hi = _LIKELY.get(likely, _LIKELY["unusual"])
    if action == "BLOCK":
        return f"Stopped. This looks like: {en}", f"रोक दिया गया। यह ऐसा लगता है: {hi}"
    if action == "HOLD":
        return f"On hold. This looks like: {en}", f"रोक कर रखा गया। यह ऐसा लगता है: {hi}"
    if action == "WARN":
        return f"Check before you pay. This could be: {en}", f"भुगतान से पहले जाँच लें। यह हो सकता है: {hi}"
    return "Looks fine", "ठीक लग रहा है"


def advice_for(likely: str) -> list[dict]:
    pairs = ADVICE.get(likely, ADVICE["unusual"]) + [LOST_MONEY]
    return [{"text_en": en, "text_hi": hi} for en, hi in pairs]
