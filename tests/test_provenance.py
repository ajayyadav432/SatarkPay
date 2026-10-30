"""What was reused from SatarkAI is exactly what docs/reused_manifest.json says, unchanged. This is what we would show the organisers."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "docs" / "reused_manifest.json").read_text(encoding="utf-8"))


def test_every_reused_file_is_byte_for_byte_what_the_manifest_records():
    changed = [p for p, info in MANIFEST["files"].items() if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != info["sha256"]]
    assert not changed, f"reused files changed: {changed}. If that was on purpose, say so in docs/REUSED_FROM_SATARKAI.md and update the manifest."


def test_the_new_detection_code_is_not_in_the_manifest():
    assert not [p for p in MANIFEST["files"] if p.startswith(("app/payments/", "ml/simulate", "ml/train", "ml/evaluate", "ml/dataset", "ml/paysim"))]
