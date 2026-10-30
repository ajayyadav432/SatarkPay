"""How the scorer does on the contents of UPI QR codes. Separate from the main results, which do not cover QR scans.

The set is small and written by hand, and it was fixed before the first run. Nothing was tuned on it. It tests what a QR says
(UPI ID, amount, note, name) with a simulated payer. It does not test reading a QR through a camera, and it says nothing about real payments.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.payments.live import Live
from ml.simulate import PERSONAS

OUT = Path(__file__).resolve().parent.parent / "models" / "qr_metrics.json"

# (UPI ID, amount, note, why it is in the set)
SCAM = [
    ("olx.buyer.help@simybl", 12000, "scan to receive", "scan to receive"),
    ("olx.payment.team@simybl", 8500, "scan and enter pin to get money", "scan to receive"),
    ("army.officer.rent@simybl", 15000, "advance refund scan to receive", "scan to receive"),
    ("buyer.quikr22@simaxis", 4999, "receive payment from buyer", "scan to receive"),
    ("refund-sbi@simybl", 2999, "refund of rs 2999 approve to receive", "fake refund"),
    ("hdfc.refund.desk@simybl", 1999, "refund processing", "fake refund"),
    ("amazon-refund-help@simybl", 2499, "order refund", "fake refund"),
    ("sbi.kyc.update@simybl", 499, "KYC fee", "fake KYC"),
    ("paytm-kyc-verify@simybl", 99, "kyc verification", "fake KYC"),
    ("rbi.safe.account@simpnb", 80000, "RBI safe account", "digital arrest"),
    ("cbi.case.clearance@simpnb", 150000, "case clearance fee", "digital arrest"),
    ("kbc.lucky.draw@simybl", 5000, "lottery processing fee", "prize"),
    ("prize.claim.office@simaxis", 2500, "claim your prize", "prize"),
    ("job.placement.hr@simybl", 25000, "joining fee", "job fee"),
    ("workfromhome.task@simybl", 3000, "task deposit", "job fee"),
    ("electricity.bill.cut@simybl", 1500, "pay now or power cut tonight", "bill threat"),
    ("rohit.k9913@simybl", 45000, "", "no words at all: a plain large payment to a new ID"),
    ("neha.s4410@simicici", 18000, "", "no words at all: a plain large payment to a new ID"),
    ("vikas.t7702@simhdfc", 6000, "advance", "ordinary word, new ID"),
    ("pooja.m2231@simaxis", 2000, "", "no words at all: a small plain payment"),
]
SAFE = [
    ("ramesh.kirana@simaxis", 180, "", "local shop"),
    ("ramesh.kirana@simaxis", 450, "groceries", "local shop"),
    ("sharma.medical@simsbi", 320, "medicines", "pharmacy"),
    ("chai.corner@simybl", 40, "", "small tea stall"),
    ("auto.driver.raju@simpaytm", 90, "", "auto fare"),
    ("milk.dairy.gupta@simsbi", 600, "milk oct", "monthly bill"),
    ("newspaper.vendor@simybl", 250, "paper bill", "monthly bill"),
    ("tiffin.service.anu@simhdfc", 2800, "tiffin october", "monthly bill"),
    ("electricity.board@simsbi", 1340, "electricity bill oct", "genuine bill word"),
    ("school.fees.office@simsbi", 12500, "school fee term 2", "large genuine fee"),
    ("dr.mehta.clinic@simicici", 800, "consultation", "doctor"),
    ("arjun.friend@simybl", 500, "dinner split", "friend"),
    ("priya.cousin@simaxis", 1500, "gift", "family"),
    ("landlord.verma@simhdfc", 9000, "rent october", "large regular payment"),
    ("gym.fitzone@simaxis", 1200, "membership", "shop"),
    ("salon.style@simybl", 350, "haircut", "shop"),
    ("petrol.pump.hp@simsbi", 1000, "", "fuel"),
    ("kirana.new.shop@simybl", 75, "", "new small shop"),
    ("temple.donation@simsbi", 501, "donation", "donation"),
    ("refund.friend.rahul@simybl", 300, "paying back", "genuine word 'refund' in an ID"),
]


def score_set(engine: Live) -> dict:
    me = PERSONAS["sunita"]["vpa"]
    acct = engine.world.users[me]
    rows = []
    for truth, group in (("scam", SCAM), ("safe", SAFE)):
        for payee, amount, note, why in group:
            entry = engine.score_request({"payer": me, "payee": payee, "amount": float(amount), "kind": "QR", "device": acct.device, "city": None, "note": note,
                                          "link": None, "balance": None, "sms": None, "sms_sender": None}, source="api", explain_always=False)
            r = entry["result"]
            engine.decide(entry["txn"]["txn_id"], "cancelled")     # nothing moved, so one QR does not change the next
            rows.append({"truth": truth, "payee": payee, "amount": amount, "note": note, "why": why, "action": r["action"], "score": r["score"]})
    scams = [r for r in rows if r["truth"] == "scam"]
    safe = [r for r in rows if r["truth"] == "safe"]
    flagged = lambda r: r["action"] != "ALLOW"
    stopped = lambda r: r["action"] in ("HOLD", "BLOCK")
    return {"set": "hand-written, fixed before the first run, not used for tuning", "scams": len(scams), "safe": len(safe),
            "scams_flagged": sum(map(flagged, scams)), "scams_stopped": sum(map(stopped, scams)),
            "safe_flagged": sum(map(flagged, safe)), "safe_stopped": sum(map(stopped, safe)),
            "missed": [r for r in scams if not flagged(r)], "false_alarms": [r for r in safe if flagged(r)], "rows": rows}


def main() -> None:
    from app.payments import store
    store.init()
    engine = Live(n_users=800, n_merchants=120, warmup_days=14)
    engine.pauses = {}
    result = score_set(engine)
    engine.shutdown()
    OUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"Scams flagged {result['scams_flagged']}/{result['scams']}, stopped {result['scams_stopped']}/{result['scams']}. "
          f"Safe flagged {result['safe_flagged']}/{result['safe']}, stopped {result['safe_stopped']}/{result['safe']}.")
    for r in result["missed"]:
        print("  missed:", r["payee"], r["amount"], repr(r["note"]), "-", r["why"], r["score"])
    for r in result["false_alarms"]:
        print("  false alarm:", r["payee"], r["amount"], repr(r["note"]), r["action"], r["score"])


if __name__ == "__main__":
    main()
