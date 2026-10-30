"""Reads the words around a payment: note, link, UPI ID and recent SMS.

The SatarkAI engine (app/analysis, unchanged) does the heavy lifting. This file adds payment knowledge the engine
does not have, because it was built for messages. Measured on the engine alone: "Approve to get cashback Rs 750"
and "scan to receive money" score Safe 0, and "paytm.cashback.offer@okaxis" scores Safe 0.
"""
from __future__ import annotations

import re
from functools import lru_cache

from app.analysis import brands
from app.analysis.extract import normalise_url
from app.analysis.pipeline import analyze, analyze_url

# Receiving money never needs a PIN, an approval or a scan. A note that says otherwise is a lie.
_RECEIVE_LURE = re.compile(
    r"\b(?:approve|accept|scan|enter|confirm)\b[^.!?\n]{0,40}\b(?:receive|get|claim|credit(?:ed)?)\b"
    r"|\bto\s+receive\b"
    r"|\b(?:refund|cashback|prize|reward|bonus|winning|lottery)\b[^.!?\n]{0,30}\b(?:approve|accept|scan|upi\s*pin)\b"
    r"|\bapprove\s*kar|\bscan\s*kar|\bpin\s*(?:daal|dal|enter)\w*|\bpaise?\s*(?:milenge|milega|paane|lene)\b"
    r"|(?:पाने|प्राप्त\s*करने|लेने)\s*के\s*लिए[^।\n]{0,30}(?:स्वीकार|मंजूर|अप्रूव|स्कैन|पिन)"
    r"|(?:स्वीकार|मंजूर|अप्रूव|स्कैन)\s*(?:करें|कीजिए|करो)",
    re.I)
_LURE_WORDS = re.compile(
    r"\b(?:refund|cashback|cash\s*back|prize|lottery|lucky\s*draw|kbc|reward|bonus|subsidy|challan|kyc|winner|winning|inaam|inam)\b"
    r"|रिफंड|इनाम|लॉटरी|केवाईसी|चालान|कैशबैक",
    re.I)
_FEE_WORDS = re.compile(
    r"\b(?:processing\s+fee|joining\s+fee|registration|security\s+deposit|safe\s+account|verification|legal|customs|clearance"
    r"|penalty|task|trading|investment|deposit)\b|सत्यापन|जमानत",
    re.I)

SCORE_RECEIVE_LURE = 85
SCORE_LURE_WORD = 45
SCORE_FEE_WORD = 30

# Real payment gateways. The engine reads paytm.me as Paytm's name on someone else's domain (High 60). In a payment
# that is a false alarm: anyone can have a gateway link, so the domain says nothing either way.
_GATEWAYS = {"rzp.io", "razorpay.com", "paytm.me", "payu.in", "cashfree.com", "instamojo.com"}

_BRANDS_THAT_ARE_SURNAMES = {"Kotak Mahindra Bank"}

# Words in a UPI ID that a shop or a person has little reason to use.
_VPA_SCAM_WORDS = {"refund", "kyc", "ekyc", "cashback", "prize", "lottery", "lucky", "kbc", "reward", "rewards", "subsidy", "verify",
                   "customercare", "helpdesk", "claim", "bonus", "offer", "winner"}


@lru_cache(maxsize=100_000)
def note_signal(note: str) -> dict:
    """Risk of the note on a payment, 0 to 100, with the words that caused it."""
    note = (note or "").strip()
    if not note:
        return {"score": 0, "receive_lure": False, "evidence": None, "reason": None}
    r = analyze(note, channel="sms")
    score, evidence, reason = r["score"], None, None
    if r["factors"]:
        top = r["factors"][0]
        reason = top["title"]
        evidence = (top.get("evidence") or [None])[0]
    lure = _RECEIVE_LURE.search(note)
    if lure:
        score, evidence, reason = max(score, SCORE_RECEIVE_LURE), lure.group(0), "Says you must act to receive money"
    else:
        word = _LURE_WORDS.search(note)
        if word and score < SCORE_LURE_WORD:
            score, evidence, reason = SCORE_LURE_WORD, word.group(0), "Uses a common scam word"
        else:
            fee = _FEE_WORDS.search(note)
            if fee and score < SCORE_FEE_WORD:
                score, evidence, reason = SCORE_FEE_WORD, fee.group(0), "Asks for a fee or deposit"
    return {"score": int(score), "receive_lure": bool(lure), "evidence": evidence, "reason": reason}


@lru_cache(maxsize=100_000)
def link_signal(url: str) -> dict:
    """Risk of the link that opened the payment. The link is only read, never opened."""
    url = (url or "").strip()
    if not url:
        return {"score": 0, "official": False, "domain": None, "display": None, "reason": None}
    r = analyze_url(normalise_url(url[:2048].replace("\\", "/")))    # browsers read a backslash as a slash: evil.com\@bank.com opens evil.com
    domain = r.get("registered_domain") or r.get("host")
    if domain in _GATEWAYS:
        return {"score": 0, "official": False, "domain": domain, "display": r.get("display"), "reason": None}
    return {"score": int(r["score"]), "official": bool(r.get("trusted")), "domain": domain,
            "display": r.get("display"), "reason": r["factors"][0]["title"] if r.get("factors") else None}


@lru_cache(maxsize=100_000)
def vpa_signal(vpa: str) -> dict:
    """Does a UPI ID imitate a brand or use scam words? Uses SatarkAI's brand list. Verified merchants are exempt (see features)."""
    local = (vpa or "").split("@")[0].lower()
    if not local:
        return {"score": 0, "brand": None, "words": []}
    label = re.sub(r"[^a-z0-9]+", "-", local).strip("-")
    host = f"{label}.invalid"
    tokens = [t for t in label.split("-") if t]
    words = sorted({t for t in tokens if t.rstrip("0123456789") in _VPA_SCAM_WORDS})
    brand = None
    for f in brands.check_host(host, host, label, ""):
        # The engine's "one letter away" test suits websites. Here it would accuse everyone named Payal of imitating
        # PayPal. In a UPI ID only a swapped character (paypa1) counts, and a brand that is also a surname needs a scam word.
        same_letters = re.sub(r"[^a-z0-9]", "", f["matched"]) == f.get("looks_like")
        if f["kind"] == "lookalike" and not same_letters and f["looks_like"] not in brands.skeletons(f["matched"]):
            continue
        if f["brand"] in _BRANDS_THAT_ARE_SURNAMES and not words:
            continue
        brand = f["brand"]
        break
    if brand and words:
        score = 80
    elif brand:
        score = 60
    elif words:
        score = 50
    else:
        score = 0
    return {"score": score, "brand": brand, "words": words}


@lru_cache(maxsize=50_000)
def sms_signal(text: str, sender: str) -> dict:
    """What the SatarkAI engine thinks of a message the user just received."""
    r = analyze(text or "", channel="sms", sender=sender or None)
    top = r["factors"][0]["title"] if r["factors"] else None
    return {"score": int(r["score"]), "level": r["level"], "category": r["category"], "reason": top,
            "vpas": tuple(v.lower() for v in r["entities"]["upi_ids"]), "domains": tuple(r["entities"]["domains"]),
            "reasons": [f["title"] for f in r["factors"][:3]]}
