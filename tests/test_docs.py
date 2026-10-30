"""The documents quote measured results. If the numbers change, the documents must change too."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
M = json.loads((ROOT / "models" / "metrics.json").read_text(encoding="utf-8"))
README = (ROOT / "README.md").read_text(encoding="utf-8")
QA = (ROOT / "docs" / "JUDGING_QA.md").read_text(encoding="utf-8")
DEMO = (ROOT / "docs" / "DEMO_SCRIPT.md").read_text(encoding="utf-8")


def pct(x, d=0):
    return f"{x * 100:.{d}f}%"


ACT = M["policy"]["test"]
LOO = {r["held_out"]: r for r in M["leave_one_scam_out"]}


@pytest.mark.parametrize("number", [pct(ACT["all_fraud"]["flagged"]), pct(ACT["all_fraud"]["stopped"]), pct(ACT["genuine"]["flagged"], 2), pct(ACT["careful_fraud"]["flagged"]),
                                    f"{M['paysim']['with_balance_columns']['pr_auc']:.3f}", f"{M['paysim']['without_balance_columns']['pr_auc']:.3f}",
                                    f"p95 {M['latency']['http']['p95_ms']} ms"])
def test_readme_quotes_the_measured_numbers(number):
    assert number in README, number


def test_the_qa_quotes_the_never_seen_results():
    r = LOO["fake_collect"]
    assert pct(r["xgb_alone_recall"]) in QA and pct(r["full_system_recall"]) in QA
    assert f"{M['systems']['isolation_forest']['pr_auc']:.3f}" in QA, "we state plainly that the forest alone is weak"


def test_the_demo_script_quotes_the_never_seen_results():
    r = LOO["fake_collect"]
    assert pct(r["xgb_alone_recall"]) in DEMO and pct(r["full_system_recall"]) in DEMO


@pytest.mark.parametrize("doc", [README, QA, DEMO])
def test_documents_never_quote_accuracy_as_a_result(doc):
    assert "99.999%" in doc or doc is QA, "the point about accuracy is made"
    for line in doc.splitlines():
        if "accura" in line.lower():
            assert any(w in line.lower() for w in ("never report", "wrong number", "never flags", "99.999", "do not report", "unknown", "said", "99% accurate", "real-world", "real payments")), line


def test_the_qr_numbers_in_the_documents_are_the_measured_ones():
    q = json.loads((ROOT / "models" / "qr_metrics.json").read_text(encoding="utf-8"))
    for text in (README, QA):
        assert f"{q['scams_flagged']} of {q['scams']}" in text and f"{q['safe_flagged']} of {q['safe']}" in text

