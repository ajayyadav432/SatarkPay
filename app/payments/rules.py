"""Hard rules: plain facts that do not need a model. Each has a weight, like the engine's evidence items.

Rules take plain numbers, so the same function runs per payment when live and over a whole table when evaluating.
"""
from __future__ import annotations

# High and Critical need more than one model's opinion. These facts count as that second voice.
P2P_COLLECT = ("p2p_collect", 0.90)      # NPCI stopped person-to-person collect requests by 1 Oct 2025 (plan.md section 5)
RECEIVE_LURE = ("receive_lure", 0.70)    # entering a PIN or approving a request always sends money, never receives it
SCAM_SMS_LINK = ("scam_sms_link", 0.60)  # a scam SMS named this payee or this link's site
SCAM_LINK = ("scam_link", 0.50)          # the link that opened the payment looks like phishing
REPORTED_MANY = ("reported_many", 0.55)  # three or more complaints against this account
FAKE_VPA = ("fake_vpa", 0.40)            # the UPI ID imitates a brand, and the account is not verified


def rule_hits(kind_collect: float, is_merchant: float, verified: float, receive_lure: float, vpa_risk: float, reports: float,
              sms_mention_risk: float, link_risk: float, link_official: float, payee_known: float) -> list[tuple[str, float]]:
    hits = []
    if kind_collect and payee_known and not is_merchant:
        hits.append(P2P_COLLECT)
    if receive_lure and not verified:
        hits.append(RECEIVE_LURE)
    if sms_mention_risk >= 60 and not link_official:   # a bill reminder, then paying on the real site, is fine
        hits.append(SCAM_SMS_LINK)
    if link_risk >= 60 and not link_official:
        hits.append(SCAM_LINK)
    if reports >= 3:    # one or two complaints are weak: 1.9% of genuine payments go to such accounts (measured). XGBoost still sees them.
        hits.append(REPORTED_MANY)
    if vpa_risk >= 60:
        hits.append(FAKE_VPA)
    return hits


def rule_hits_for(f: dict) -> list[tuple[str, float]]:
    return rule_hits(f["kind_collect"], f["payee_is_merchant"], f["payee_verified"], f["receive_lure"], f["vpa_risk"], f["payee_reports_30d"],
                     f["sms_mentions_payee"], f["link_risk"], f["link_official"], f["payee_known"])


def combined_rule_weight(hits: list[tuple[str, float]]) -> float:
    remaining = 1.0
    for _, w in hits:
        remaining *= 1.0 - w
    return 1.0 - remaining
