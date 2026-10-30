"""Scores one payment from start to finish: features, two models, hard rules, one score, an action, and the reasons."""
from __future__ import annotations

import threading
import time

import numpy as np

from app import config
from app.payments import explain, policy
from app.payments.context import link_signal, note_signal, vpa_signal
from app.payments.features import FEATURES, FeatureStore
from app.payments.models import Ensemble, ensemble, fuse
from app.payments.rules import combined_rule_weight, rule_hits_for


def level_for(score: float) -> str:
    name = config.RISK_LEVELS[0][0]
    for level, lowest in config.RISK_LEVELS:
        if score >= lowest:
            name = level
    return name


class Scorer:
    """Owns the feature store. Everything that changes the store goes through a lock, as the API and the stream share it."""

    def __init__(self, store: FeatureStore | None = None, models: Ensemble | None = None):
        self.store = store if store is not None else FeatureStore()
        self.models = models or ensemble()
        self.lock = threading.RLock()

    def score(self, txn: dict, explain_always: bool = False) -> dict:
        """Read-only: scoring a payment does not record it. Call observe() when it has happened."""
        started = time.perf_counter()
        link = link_signal(txn.get("link") or "")
        with self.lock:
            f = self.store.features_for(txn)
            sms = self.store.recent_sms(txn["payer"], txn["payee"], link["domain"], txn["ts"], self.store.one_off_sms(txn))
            last_city = self.store.accounts[txn["payer"]].last_city
        x = np.array([f[n] for n in FEATURES], dtype=np.float32)
        m = self.models
        p = m.probability(x)
        pct, w_a = m.anomaly(x)
        rules = rule_hits_for(f)
        w_r = combined_rule_weight(rules)
        risk = float(fuse(p, w_a, w_r))
        score = int(round(float(m.bands.score(risk))))     # the number a person sees is the number the policy uses
        layers = policy.layers_agreeing(p, pct, w_r)
        plain_fact = w_r >= policy.PLAIN_FACT
        action = policy.decide_action(score, f["amount"], layers, plain_fact)

        result = {
            "txn_id": txn.get("txn_id"), "score": score, "level": level_for(score), "action": action,
            "stopped": action in (policy.HOLD, policy.BLOCK), "alert": action != policy.ALLOW,
            "model": {"xgb_probability": round(p, 4), "anomaly_percentile": round(pct, 5), "anomaly_weight": round(w_a, 4),
                      "rule_weight": round(w_r, 4), "risk": round(risk, 4), "layers_agreeing": layers},
            "rules": [r for r, _ in rules],
        }
        if result["alert"] or explain_always:
            ctx = {"note": note_signal(txn.get("note") or ""), "link": link, "vpa": vpa_signal(txn["payee"]),
                   "sms": sms, "last_city": last_city}
            values, base = m.shap_values(x)
            reasons, weights = explain.build_reasons(txn, f, values, rules, pct, ctx, m.normal)
            likely = explain.likely_type(txn, f, rules, weights)
            head_en, head_hi = explain.headline(action, likely)
            result.update({"headline_en": head_en, "headline_hi": head_hi, "likely": likely, "reasons": reasons,
                           "advice": explain.advice_for(likely), "shap": explain.waterfall(values, base), "values": _public_values(f)})
        else:
            result.update({"headline_en": "Looks fine", "headline_hi": "ठीक लग रहा है", "likely": None, "reasons": [], "advice": [], "shap": None})
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return result

    def observe(self, ev: dict, moved: bool = True) -> None:
        with self.lock:
            self.store.observe(ev, moved=moved)

    def record_sms(self, user: str, text: str, sender: str, ts: float) -> dict:
        with self.lock:
            return self.store.record_sms(user, text, sender, ts)


def _public_values(f: dict) -> dict:
    """The numbers behind the reasons, for the analyst. Missing values become null, which JSON can carry."""
    keep = ("amount", "amt_vs_median", "amt_to_balance", "new_payee", "new_device", "km_from_last", "out_count_1h", "payee_age_days", "payee_unique_in_24h",
            "payee_first_time_share", "payee_passthrough", "payee_collects_24h", "payee_decline_share", "payee_reports_30d", "forward_ratio",
            "payer_unique_in_24h", "note_risk", "link_risk", "vpa_risk", "sms_risk_15m", "device_accounts")
    out = {}
    for k in keep:
        v = f[k]
        out[k] = None if isinstance(v, float) and v != v else round(float(v), 3)
    return out
