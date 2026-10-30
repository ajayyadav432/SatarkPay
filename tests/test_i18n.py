"""Every sentence the system can say has a translation, and its real numbers survive."""
import re

import pytest

from app.main import apply_reputation
from app.payments import explain, i18n

SENTENCES = [
    "₹5,000 is 12 times your usual payment of ₹400", "This would take 80% of your balance", "You have never paid bad@ybl before",
    "3 payments from this account in the last hour, ₹9,000 in total", "This is at an hour when you rarely pay", "This payment comes from a phone you have not used before",
    "4 different UPI accounts have been used on this phone", "Your last payment was 1,200 km from here, in Jaipur",
    "This account received ₹9,000 from 1 person in 24 hours and is now sending 90% of it out", "This account received ₹9,000 from 5 people in 24 hours and is now sending 90% of it out",
    "This account is only 1 day old", "This account is only 9 days old", "Nothing is known about this UPI ID", "This is not a verified merchant",
    "7 different people paid this account in the last 24 hours", "70% of the money this account received has already left it, which is typical of mule accounts",
    "7 people got a request from this account today, and 50% of those who answered declined it", "7 people got a request from this account today",
    "1 person has reported this account", "6 people have reported this account", "The note says \"get paid\". Entering your PIN always sends money, it never receives it",
    "The note says \"urgent {x}\", which is common in scams", "This payment was opened from a link on bad.in, which is not an official site",
    "This UPI ID uses the name of SBI, but it is not their account", "This UPI ID uses scam words such as \"refund\"",
    "You got a suspicious SMS just now", "You got a suspicious SMS 1 minute ago that points to this payment", "You got a suspicious SMS 5 minutes ago", "You got a suspicious SMS 3 hours ago",
    "Overall, this payment is more unusual than 99.5% of normal payments",
]


def all_fixed_sentences():
    out = [en for en, _ in explain.RULE_REASONS.values()] + [explain.LOST_MONEY[0]]
    out += [en for rows in explain.ADVICE.values() for en, _ in rows]
    out += [row[2] for row in explain._UNUSUAL]
    out += [explain.headline(action, key)[0] for action in ("ALLOW", "WARN", "HOLD", "BLOCK") for key, _, _ in explain.LIKELY]
    return out


@pytest.mark.parametrize("lang", i18n.LANGS)
def test_every_sentence_has_a_translation(lang):
    untranslated = [s for s in SENTENCES + all_fixed_sentences() if i18n.translate(s, lang) == s]
    assert not untranslated


@pytest.mark.parametrize("lang", i18n.LANGS)
def test_numbers_and_names_survive(lang):
    out = i18n.translate("₹5,000 is 12 times your usual payment of ₹400", lang)
    assert "₹5,000" in out and "12" in out and "₹400" in out
    assert "bad@ybl" in i18n.translate("You have never paid bad@ybl before", lang)
    assert "urgent {x}" in i18n.translate("The note says \"urgent {x}\", which is common in scams", lang)


@pytest.mark.parametrize("lang", i18n.LANGS)
def test_reputation_reasons_are_translated(lang, monkeypatch):
    from app.payments import store
    for blocked, count in ((True, 5), (False, 5)):
        monkeypatch.setattr(store, "get_block", lambda _p, b=blocked: {"reason": "x"} if b else None)
        monkeypatch.setattr(store, "report_count", lambda _p, c=count: c)
        result = {"action": "ALLOW", "score": 5, "level": "Safe", "reasons": [], "advice": [], "headline_en": "Looks fine", "stopped": False, "alert": False}
        apply_reputation(result, "x@simbank")
        i18n.localise(result)
        assert result[f"headline_{lang}"] != result["headline_en"]
        assert result["reasons"][0][f"text_{lang}"] != result["reasons"][0]["text_en"]


def test_an_unknown_sentence_stays_english():
    assert i18n.translate("Something new", "ta") == "Something new"
    assert i18n.translate("Looks fine", "hi") == "Looks fine"


def test_web_strings_cover_the_same_words_in_every_language():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "app/static/strings.js").read_text(encoding="utf-8")
    pages = text[text.index("window.SP_PAGES"):]
    keys = [set(re.findall(r"(?:\{|, )(\w+): (?:\"|\()", line)) for line in pages.splitlines() if re.match(r"\s+(en|hi|bn|mr|ta|te): \{", line)]
    assert len(keys) == 6 and all(k == keys[0] for k in keys)
