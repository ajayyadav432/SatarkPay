"""Central settings. Change the app name here and it changes everywhere."""
import os
from pathlib import Path

APP_NAME = "SatarkPay"
APP_TAGLINE = "Stops a scam payment before the money is gone, and says why"
PROBLEM_STATEMENT = "SPHINX'26 PS 3.2: Real-Time Fraud Detection for UPI and Digital Payments"

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
STATIC_DIR = APP_DIR / "static"
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "ml" / "engine"          # the reused SatarkPay text and URL models, unchanged
KNOWLEDGE_DIR = APP_DIR / "data"               # the reused SatarkPay rules and brand lists, unchanged

PAY_MODELS_DIR = ROOT / "models"               # SatarkPay's own models and metrics.json
XGB_FILE = PAY_MODELS_DIR / "xgb.ubj"
IFOREST_FILE = PAY_MODELS_DIR / "iforest.joblib"
BUNDLE_FILE = PAY_MODELS_DIR / "bundle.json"   # feature order, thresholds, normal ranges
METRICS_FILE = PAY_MODELS_DIR / "metrics.json"

# Tests point this at a temporary file so they never touch real alerts.
DB_PATH = Path(os.environ.get("SATARKPAY_DB", DATA_DIR / "alerts.db"))

HOST = os.environ.get("SATARK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SATARK_PORT", "8000"))


def env(key: str, default: str | None = None) -> str | None:
    """A setting from the environment, else from the project's .env file (never committed)."""
    if os.environ.get(key):
        return os.environ[key]
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == key and v.strip():
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return default


LOOPBACK = {"127.0.0.1", "::1", "localhost"}

# Input limits (the reused engine reads the first four)
MAX_TEXT_CHARS = 20_000
MAX_SENDER_CHARS = 320
MAX_URLS_PER_MESSAGE = 25
MAX_URL_CHARS = 2_048
MAX_NOTE_CHARS = 200
MAX_VPA_CHARS = 120

# Risk levels: (name, lowest score in the level). The same five levels as the engine.
RISK_LEVELS = [
    ("Safe", 0),
    ("Low", 20),
    ("Medium", 40),
    ("High", 60),
    ("Critical", 80),
]

CHANNELS = ["sms", "email", "social", "url"]

# the engine's warning page asks for confirmation from this level upwards (kept for the reused extension).
WARN_FROM_LEVEL = "Medium"

# Reported UPI fraud, used only for the real-world correction on the model card.
# Sources are listed in plan.md section 5.
REAL_FRAUD_INCIDENTS_FY25 = 1_264_000
REAL_UPI_TRANSACTIONS_FY25 = 185_800_000_000
