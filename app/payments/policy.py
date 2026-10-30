"""What to do with a payment, once its score is known.

This is the most important business decision in the system, and the first thing a judge will question.
A false alarm annoys one person. A missed scam can take someone's savings. And scams are so rare in real life (about
7 in a million payments) that most alerts will be false however good the model is. So the rules are:

    - a warning is cheap, because the user stays in control
    - stopping a payment is expensive, so it needs money at stake
    - refusing outright needs independent layers to agree, or a plain fact. A model's opinion alone is never enough.
"""
from __future__ import annotations

ALLOW, WARN, HOLD, BLOCK = "ALLOW", "WARN", "HOLD", "BLOCK"
ACTIONS = [ALLOW, WARN, HOLD, BLOCK]

# The score bands are set on validation data (see ml/train.py): 40 is the top 1% of genuine payments, 60 the top 0.2%,
# 80 the top 0.05%.
WARN_FROM = 40
HOLD_FROM = 60
BLOCK_FROM = 80
# Below this, stopping the payment costs the user more trust than the money at risk is worth. They still get a warning.
SMALL_AMOUNT = 200.0

# The person stays in control, but a pause helps them step out of the scammer's pressure. On hold, this short wait
# stands in for a real cooling-off period. A blocked payment cannot be continued at all, only reviewed by the bank.
PAUSE_SECONDS = {WARN: 5, HOLD: 15}

MODEL_SUSPICIOUS = 0.50      # XGBoost's probability at which it counts as one voice
ANOMALY_SUSPICIOUS = 0.99    # higher than this share of normal payments: the anomaly model counts as one voice
RULE_SUSPICIOUS = 0.40       # a hard rule at least this strong counts as one voice
PLAIN_FACT = 0.70            # a rule this strong is a fact, not an opinion: see rules.py


def layers_agreeing(p: float, anomaly_pct: float, rule_weight: float) -> int:
    """How many independent layers find this payment suspicious: the trained model, the anomaly model, the hard rules."""
    return int(p >= MODEL_SUSPICIOUS) + int(anomaly_pct >= ANOMALY_SUSPICIOUS) + int(rule_weight >= RULE_SUSPICIOUS)


def decide_action(score: float, amount: float, layers: int, plain_fact: bool) -> str:
    """ALLOW, WARN, HOLD or BLOCK. Higher risk must never give a softer action, and that is tested."""
    if score < WARN_FROM:
        return ALLOW
    if plain_fact and score >= BLOCK_FROM:
        return BLOCK
    if amount < SMALL_AMOUNT:
        return WARN
    if score >= BLOCK_FROM and layers >= 2:
        return BLOCK
    if score >= HOLD_FROM:
        return HOLD
    return WARN
