"""Shared fixtures. Every test run uses its own temporary database, never the real alerts."""
import base64
import hashlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Must be set before app.config is imported.
_TMP = tempfile.mkdtemp(prefix="satarkpay-test-")
os.environ["SATARKPAY_DB"] = str(Path(_TMP) / "test.db")
os.environ["SATARK_TOKEN"] = "test-pairing-code"
os.environ["SATARKPAY_AUTOSTART"] = "0"
TEST_PASSWORD = "test-password"
_salt = b"0123456789abcdef"
_hash = "scrypt." + base64.urlsafe_b64encode(_salt).decode() + "." + base64.urlsafe_b64encode(hashlib.scrypt(TEST_PASSWORD.encode(), salt=_salt, n=2**14, r=8, p=1)).decode()
os.environ["SATARK_PASS_USER"] = os.environ["SATARK_PASS_MERCHANT"] = os.environ["SATARK_PASS_ADMIN"] = _hash

import pytest  # noqa: E402

from app.analysis import models  # noqa: E402

# The engine tests copied from SatarkPay read these names from here.
MODELS_READY = all(models.status().values())
needs_models = pytest.mark.skipif(not MODELS_READY, reason="SatarkPay models missing in ml/engine")

SCAM_KYC = "Dear customer, your SBI account will be blocked today. Update your KYC immediately: http://sbi-kyc-update.xyz/login"
SCAM_BILL = ("Dear Consumer, your electricity power will be disconnected tonight at 9.30 pm because your previous month "
             "bill was not updated. Please contact our electricity officer 9876543210 immediately.")
SCAM_LOTTERY = ("Congratulations! You have won Rs 25,00,000 in KBC lucky draw. To claim your prize pay processing fee "
                "Rs 5,000 to kbcoffice@ybl. Call 8765432109")
SCAM_ARREST = ("This is Inspector Sharma from CBI. Your Aadhaar is linked to a money laundering case. You are under "
               "digital arrest. Join the video call now and do not tell anyone. Transfer Rs 2,00,000 for verification.")
SCAM_HINGLISH = "Priya grahak, aapka HDFC khata band ho jayega. Turant KYC update karein, link par click karein: hdfc-kyc.co.in/verify"
SCAM_HINDI = "प्रिय ग्राहक, आपका एसबीआई खाता आज बंद हो जाएगा। तुरंत केवाईसी अपडेट करने के लिए नीचे दिए गए लिंक पर क्लिक करें: https://sbi-kyc.in/update"
OK_OTP = "482913 is your OTP for transaction of INR 2,499.00 at AMAZON. Do not share it with anyone. -HDFC Bank"
OK_DEBIT = "Rs 5,000.00 debited from A/c XX1234 on 12-Oct-26. Avl Bal Rs 12,340.55. If not you, call 18001234567 -SBI"
OK_CHAT = "Hey are we still meeting for lunch tomorrow at 1? Let me know"
OK_ORDER = "Your Amazon order #402-1234567 has been shipped and will arrive tomorrow. Track: https://www.amazon.in/gp/your-account/order-details"


@pytest.fixture()
def client():
    """Only the engine's own /api/model-card test asks for this; that page is not part of SatarkPay."""
    pytest.skip("the engine's model-card page is not part of SatarkPay")


@pytest.fixture(scope="session")
def engine():
    """One small live world for the whole test run. The stream thread stays off, so tests step it by hand."""
    from app import main

    main.live = main.Live(n_users=800, n_merchants=120, warmup_days=14)
    main.live.pauses = {}       # tests do not sit through the pause; one test checks it directly
    return main.live


@pytest.fixture()
def api(engine):
    from fastapi.testclient import TestClient

    from app.main import app
    engine.running = False
    class WithToken(TestClient):
        """Fills in the payment's token, which a real caller gets from /score. tests/test_api.py checks the refusal."""

        def post(self, url, **kw):
            body = kw.get("json")
            if url == "/api/v1/outcome" and body and "token" not in body:
                kw["json"] = {**body, "token": engine.pending.get(body["txn_id"], {}).get("token", "none")}
            return super().post(url, **kw)

    with WithToken(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as c:
        assert c.post("/api/v1/auth/login", json={"role": "admin", "username": "admin", "password": TEST_PASSWORD}).status_code == 200     # as if on the laptop running the demo
        yield c
    engine.running = False
