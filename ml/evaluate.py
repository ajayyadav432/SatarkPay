"""Measure the system honestly and write every number to models/metrics.json. Nothing here changes the models.

    python -m ml.evaluate

The test set is later days of the training world plus a completely new world: new users, new shops, new scammers.
Any scammer account that also appeared in the training or validation period is removed from the test.
We never report accuracy. Fraud is so rare that a model which never flags anything scores 99.9%.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import average_precision_score, roc_auc_score

from app import config
from app.payments.features import CONTEXT, FEATURES, MOVER, PAYEE, PAYER
from app.payments.models import ANOMALY_FULL, ANOMALY_MAX_WEIGHT, ANOMALY_START, Bands, anomaly_weight, fuse
from app.payments.policy import decide_action, layers_agreeing
from ml.simulate import WorldConfig
from ml.train import (BUDGETS, SEED, TEST_DAYS, TRAIN_DAYS, UNREPORTED_SHARE, VAL_DAYS, XGB_PARAMS, fit_xgb, forest_percentiles, full_risk,
                      predict_xgb, rule_weights, split, with_unreported_scams, world_table)

TYPOLOGIES = ["fake_collect", "phishing_link", "qr_scam", "mule_inflow", "mule_layering", "account_takeover", "coached_transfer"]
# Seeds 1001 and 2002 were looked at while the fusion was being designed, so they are no longer used for results.
NEW_WORLD = WorldConfig(seed=3003, days=30)
NEW_WORLD_TEST_DAYS = (10, 29)
STEALTH_WORLD = WorldConfig(seed=4004, days=25, stealth=0.9)
STEALTH_TEST_DAYS = (10, 24)
FPR_POINTS = (0.0001, 0.001, 0.005, 0.01)
HARD_NEGATIVE_NAMES = {
    "hn_trip_pool": "Pooling money for a trip, then paying once",
    "hn_shop": "Shop owner on a personal UPI ID",
    "hn_first_rent": "First rent payment to a new person",
    "hn_big_purchase": "First big purchase at a new merchant",
    "hn_big_known": "Large emergency transfer to a known person",
    "hn_new_phone": "New phone",
    "hn_travel": "Travelling to another city",
    "hn_fair": "A shop's very busy day at a fair",
    "hn_new_shop": "A newly opened shop",
    "hn_note": "A genuine note saying refund",
    "hn_bill_sms": "Alarming bill reminder, then the real bill payment",
    "hn_forward": "Parent sends money, student pays the fee an hour later",
}
IST = timezone(timedelta(hours=5, minutes=30))


def fresh_scammers_only(test: pd.DataFrame, seen: set) -> tuple[pd.DataFrame, int]:
    """A scammer already seen in training proves nothing about new scammers."""
    known = test["label"].eq(1) & (test["payee"].isin(seen) | (test["payer"].isin(seen) & test["typology"].eq("mule_layering")))
    return test[~known], int(known.sum())


def threshold_for_fpr(score: np.ndarray, is_genuine: np.ndarray, fpr: float) -> float:
    return float(np.quantile(score[is_genuine], 1 - fpr))


def recall_at(score, y, t) -> float:
    return float((score[y == 1] >= t).mean()) if (y == 1).any() else float("nan")


def rate_at(score, y, t) -> float:
    return float((score[y == 0] >= t).mean())


def summary(score: np.ndarray, y: np.ndarray, amount: np.ndarray) -> dict:
    out = {"pr_auc": float(average_precision_score(y, score)), "roc_auc": float(roc_auc_score(y, score)), "at_false_alarm_rate": {}}
    for fpr in FPR_POINTS:
        t = threshold_for_fpr(score, y == 0, fpr)
        hit = score >= t
        flagged = int(hit.sum())
        out["at_false_alarm_rate"][str(fpr)] = {
            "recall": recall_at(score, y, t), "precision": float((y[hit] == 1).mean()) if flagged else 0.0,
            "money_recall": float(amount[(y == 1) & hit].sum() / max(amount[y == 1].sum(), 1.0))}
    return out


def score_table(df: pd.DataFrame, booster, forest, medians, quantiles) -> pd.DataFrame:
    df = df.copy()
    df["p"] = predict_xgb(booster, df)
    df["pct"] = forest_percentiles(forest, medians, quantiles, df)
    df["w_a"] = anomaly_weight(df["pct"].to_numpy())
    df["w_r"] = rule_weights(df)
    df["risk"] = fuse(df["p"].to_numpy(), df["w_a"].to_numpy(), df["w_r"].to_numpy())
    return df


def actions_for(df: pd.DataFrame, bands: Bands) -> pd.DataFrame:
    """The real policy, applied row by row, so what is reported is what the live system does."""
    df = df.copy()
    df["score"] = np.round(bands.score(df["risk"].to_numpy()))     # the same whole number the live scorer uses
    actions, layers = [], []
    for score, amount, p, pct, w_r in zip(df["score"].tolist(), df["amount_raw"].tolist(), df["p"].tolist(), df["pct"].tolist(), df["w_r"].tolist()):
        n = layers_agreeing(p, pct, w_r)
        layers.append(n)
        actions.append(decide_action(score, amount, n, w_r >= 0.70))
    df["action"], df["layers"] = actions, layers
    return df


def action_table(df: pd.DataFrame) -> dict:
    """Share of payments per action, for scams by type and for genuine payments."""
    order = ["ALLOW", "WARN", "HOLD", "BLOCK"]

    def shares(part: pd.DataFrame) -> dict:
        return {"n": int(len(part)), **{a: float((part["action"] == a).mean()) if len(part) else 0.0 for a in order},
                "flagged": float(part["action"].isin(["WARN", "HOLD", "BLOCK"]).mean()) if len(part) else 0.0,
                "stopped": float(part["action"].isin(["HOLD", "BLOCK"]).mean()) if len(part) else 0.0}

    fraud = df[df["label"] == 1]
    return {"genuine": shares(df[df["label"] == 0]), "all_fraud": shares(fraud),
            "obvious_fraud": shares(fraud[~fraud["stealth"]]), "careful_fraud": shares(fraud[fraud["stealth"]]),
            "by_type": {t: shares(fraud[fraud["typology"] == t]) for t in TYPOLOGIES if (fraud["typology"] == t).any()},
            "by_type_careful": {t: shares(fraud[(fraud["typology"] == t) & fraud["stealth"]]) for t in TYPOLOGIES if ((fraud["typology"] == t) & fraud["stealth"]).any()},
            "money": {"fraud_total": float(fraud["amount_raw"].sum()),
                      "flagged": float(fraud.loc[fraud["action"].isin(["WARN", "HOLD", "BLOCK"]), "amount_raw"].sum()),
                      "stopped": float(fraud.loc[fraud["action"].isin(["HOLD", "BLOCK"]), "amount_raw"].sum())}}


def layer_table(train, val, test, forest, medians, quantiles) -> list[dict]:
    """What does each layer add? Each row retrains XGBoost on more features, at the same 1% false-alarm budget."""
    y, amount = test["label"].to_numpy(), test["amount_raw"].to_numpy()
    rows = []
    steps = [("Payer behaviour only", PAYER), ("+ the account's own money moves", PAYER + MOVER), ("+ payee signals (mules)", PAYER + MOVER + PAYEE),
             ("+ Context engine (note, link, UPI ID, SMS)", FEATURES)]
    full_p = None
    for name, feats in steps:
        booster = fit_xgb(train, val, features=feats)
        p = predict_xgb(booster, test, features=feats)
        s = summary(p, y, amount)
        rows.append({"layers": name, "n_features": len(feats), "pr_auc": s["pr_auc"], **{f"recall_at_{k}": v["recall"] for k, v in s["at_false_alarm_rate"].items()}})
        print(f"  {name:48} PR-AUC {s['pr_auc']:.3f}  recall at 1% false alarms {s['at_false_alarm_rate']['0.01']['recall']:.3f}", flush=True)
        full_p = p
    pct = forest_percentiles(forest, medians, quantiles, test)
    risk = fuse(full_p, anomaly_weight(pct), rule_weights(test))
    s = summary(risk, y, amount)
    rows.append({"layers": "+ Isolation Forest and hard rules (the full system)", "n_features": len(FEATURES), "pr_auc": s["pr_auc"],
                 **{f"recall_at_{k}": v["recall"] for k, v in s["at_false_alarm_rate"].items()}})
    print(f"  {'+ Isolation Forest and hard rules':48} PR-AUC {s['pr_auc']:.3f}  recall at 1% false alarms {s['at_false_alarm_rate']['0.01']['recall']:.3f}", flush=True)
    a = summary(pct, y, amount)
    rows.append({"layers": "Isolation Forest alone (no labels at all)", "n_features": len(forest.feature_importances_) if hasattr(forest, "feature_importances_") else None,
                 "pr_auc": a["pr_auc"], **{f"recall_at_{k}": v["recall"] for k, v in a["at_false_alarm_rate"].items()}})
    print(f"  {'Isolation Forest alone (no labels at all)':48} PR-AUC {a['pr_auc']:.3f}  recall at 1% false alarms {a['at_false_alarm_rate']['0.01']['recall']:.3f}", flush=True)
    return rows


def leave_one_scam_out(train, val, test, forest, medians, quantiles) -> list[dict]:
    """Our test for scams nobody has seen. Train with no example of one type, then see what still catches it.
    The budget is fixed on validation data, 1% false alarms, so no system gets an unfair threshold."""
    rows = []
    val_rule = rule_weights(val)
    val_w_a = anomaly_weight(forest_percentiles(forest, medians, quantiles, val))
    test_rule = rule_weights(test)
    pct_test = forest_percentiles(forest, medians, quantiles, test)
    test_w_a = anomaly_weight(pct_test)
    for typ in TYPOLOGIES:
        keep_tr = train[train["typology"] != typ]
        keep_va = val[val["typology"] != typ]
        booster = fit_xgb(keep_tr, keep_va)
        p_val = predict_xgb(booster, val)
        p_test = predict_xgb(booster, test)
        genuine_val = val["label"].to_numpy() == 0
        t_x = threshold_for_fpr(p_val, genuine_val, 0.01)
        risk_val = fuse(p_val, val_w_a, val_rule)
        t_e = threshold_for_fpr(risk_val, genuine_val, 0.01)
        risk_test = fuse(p_test, test_w_a, test_rule)
        mask = (test["typology"] == typ).to_numpy()
        genuine_test = test["label"].to_numpy() == 0
        row = {"held_out": typ, "n_test": int(mask.sum()), "xgb_alone_recall": float((p_test[mask] >= t_x).mean()),
               "full_system_recall": float((risk_test[mask] >= t_e).mean()), "xgb_alone_false_alarms": float((p_test[genuine_test] >= t_x).mean()),
               "full_system_false_alarms": float((risk_test[genuine_test] >= t_e).mean()),
               "anomaly_alone_recall": float((pct_test[mask] >= ANOMALY_START).mean())}
        rows.append(row)
        print(f"  without {typ:18} n={row['n_test']:5}  XGBoost alone {row['xgb_alone_recall']:.2f}   full system {row['full_system_recall']:.2f}   anomaly alone {row['anomaly_alone_recall']:.2f}", flush=True)
    return rows


def false_alarms_by_group(df: pd.DataFrame) -> dict:
    genuine = df[df["label"] == 0]
    out = {}
    for tag, name in HARD_NEGATIVE_NAMES.items():
        part = genuine[genuine["tag"] == tag]
        if len(part):
            out[tag] = {"name": name, "n": int(len(part)), "flagged": float(part["action"].isin(["WARN", "HOLD", "BLOCK"]).mean()),
                        "stopped": float(part["action"].isin(["HOLD", "BLOCK"]).mean())}
    shops = genuine[genuine["payee_is_merchant"] == 1]
    out["all_merchants"] = {"name": "All payments to merchants", "n": int(len(shops)), "flagged": float(shops["action"].isin(["WARN", "HOLD", "BLOCK"]).mean()),
                            "stopped": float(shops["action"].isin(["HOLD", "BLOCK"]).mean())}
    small = genuine[(genuine["payee_is_merchant"] == 1) & (genuine["payee_verified"] == 0)]
    out["small_unverified_merchants"] = {"name": "Small unverified merchants", "n": int(len(small)), "flagged": float(small["action"].isin(["WARN", "HOLD", "BLOCK"]).mean()),
                                         "stopped": float(small["action"].isin(["HOLD", "BLOCK"]).mean())}
    return out


def scored_guess_accuracy(df: pd.DataFrame) -> dict:
    """How often the 'this looks like...' line names the right scam, among scams that were flagged."""
    from app.payments import explain
    mapping = {"fake_collect": {"fake_collect"}, "phishing_link": {"phishing"}, "qr_scam": {"qr"}, "mule_inflow": {"mule", "coached"}, "mule_layering": {"forward"},
               "account_takeover": {"takeover"}, "coached_transfer": {"coached", "mule"}}
    flagged = df[(df["label"] == 1) & df["action"].isin(["WARN", "HOLD", "BLOCK"])]
    out, right_total = {}, 0
    for typ, group in flagged.groupby("typology"):
        right = 0
        for row in group.to_dict("records"):
            t = {"payee": row["payee"]}
            guess = explain.likely_type(t, row, [], {"forwarding": 1.0, "jump": 1.0})
            right += guess in mapping[typ]
        out[typ] = right / len(group)
        right_total += right
    out["all"] = right_total / max(len(flagged), 1)
    return out


def real_world_correction(recall: float, false_alarm: float) -> dict:
    """Precision if fraud were as rare as the reported figures, by Bayes. Our test set has far more fraud than real life."""
    rate = config.REAL_FRAUD_INCIDENTS_FY25 / config.REAL_UPI_TRANSACTIONS_FY25
    true_hits = recall * rate
    false_hits = false_alarm * (1 - rate)
    precision = true_hits / max(true_hits + false_hits, 1e-30)
    return {"reported_fraud_rate": rate, "per_million": rate * 1e6, "recall": recall, "false_alarm_rate": false_alarm, "precision": precision,
            "false_alarms_per_real_fraud": (false_hits / true_hits) if true_hits else None,
            "alerts_per_million_payments": (true_hits + false_hits) * 1e6}


def main(refresh: bool = False) -> None:
    started = time.time()
    booster = xgb.Booster()
    booster.load_model(config.XGB_FILE)
    booster.best_iteration = booster.num_boosted_rounds() - 1
    forest = joblib.load(config.IFOREST_FILE)
    bundle = json.loads(config.BUNDLE_FILE.read_text(encoding="utf-8"))
    medians, quantiles = np.array(bundle["anomaly_medians"]), np.array(bundle["anomaly_quantiles"])
    bands = Bands(bundle["bands"])

    print("Worlds...", flush=True)
    main_world = with_unreported_scams(world_table(WorldConfig(seed=SEED), "world42"))
    train, val = split(main_world, TRAIN_DAYS), split(main_world, VAL_DAYS)
    new_world = world_table(NEW_WORLD, f"world{NEW_WORLD.seed}", refresh)
    stealth_world = world_table(STEALTH_WORLD, f"world{STEALTH_WORLD.seed}", refresh)

    seen = set(train.loc[train["label"] == 1, "payee"]) | set(val.loc[val["label"] == 1, "payee"])
    seen |= set(train.loc[train["typology"] == "mule_layering", "payer"]) | set(val.loc[val["typology"] == "mule_layering", "payer"])
    later, removed = fresh_scammers_only(split(main_world, TEST_DAYS), seen)
    test = pd.concat([later.drop(columns=["label_seen"]), split(new_world, NEW_WORLD_TEST_DAYS)], ignore_index=True)
    y, amount = test["label"].to_numpy(), test["amount_raw"].to_numpy()
    print(f"Test: {len(test):,} payments, {int(y.sum()):,} scams ({y.mean():.2%}); {removed} removed because the scammer was seen before", flush=True)

    scored = actions_for(score_table(test, booster, forest, medians, quantiles), bands)
    systems = {"xgboost": summary(scored["p"].to_numpy(), y, amount), "isolation_forest": summary(scored["pct"].to_numpy(), y, amount),
               "full_system": summary(scored["risk"].to_numpy(), y, amount)}
    for name, s in systems.items():
        print(f"  {name:18} PR-AUC {s['pr_auc']:.3f}  ROC-AUC {s['roc_auc']:.3f}  recall at 0.01 / 0.1 / 0.5 / 1% false alarms: "
              + " / ".join(f"{s['at_false_alarm_rate'][str(k)]['recall']:.2f}" for k in FPR_POINTS), flush=True)
    actions = action_table(scored)
    g, f = actions["genuine"], actions["all_fraud"]
    print(f"  Policy: genuine flagged {g['flagged']:.3%}, stopped {g['stopped']:.3%} | scams flagged {f['flagged']:.1%}, stopped {f['stopped']:.1%}", flush=True)
    for t, r in actions["by_type"].items():
        print(f"    {t:18} n={r['n']:5}  flagged {r['flagged']:.0%}  stopped {r['stopped']:.0%}", flush=True)
    print(f"    obvious scams flagged {actions['obvious_fraud']['flagged']:.1%}, careful scams flagged {actions['careful_fraud']['flagged']:.1%}", flush=True)

    print("What each layer adds...", flush=True)
    layers = layer_table(train, val, test, forest, medians, quantiles)
    print("Leave one scam type out...", flush=True)
    loo = leave_one_scam_out(train, val, test, forest, medians, quantiles)

    print("Careful scammers (drift)...", flush=True)
    drift = actions_for(score_table(split(stealth_world, STEALTH_TEST_DAYS), booster, forest, medians, quantiles), bands)
    drift_actions = action_table(drift)
    print(f"  in a world where {STEALTH_WORLD.stealth:.0%} of scams are careful: flagged {drift_actions['all_fraud']['flagged']:.1%}, stopped {drift_actions['all_fraud']['stopped']:.1%}, "
          f"genuine flagged {drift_actions['genuine']['flagged']:.3%}", flush=True)

    groups = false_alarms_by_group(scored)
    correction = real_world_correction(f["flagged"], g["flagged"])
    correction_stop = real_world_correction(f["stopped"], g["stopped"])
    correction_block = real_world_correction(f["BLOCK"], g["BLOCK"])
    guess_right = scored_guess_accuracy(scored)

    gain = booster.get_score(importance_type="total_gain")
    total = sum(gain.values())
    metrics = {
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"),
        "versions": {"xgboost": xgb.__version__, "seed": SEED},
        "data": {
            "note": "Everything here is synthetic: a simulated world written by the team. Real-world performance is unknown.",
            "test_payments": int(len(test)), "test_scams": int(y.sum()), "test_fraud_share": float(y.mean()), "removed_known_scammers": removed,
            "train_payments": int(len(train)), "train_scams": int(train["label"].sum()), "validation_payments": int(len(val)), "validation_scams": int(val["label"].sum()),
            "unreported_share_in_training": UNREPORTED_SHARE, "stealth_share": WorldConfig().stealth, "n_features": len(FEATURES),
            "real_fraud_rate_note": "Reported UPI fraud is far rarer than in this simulation, which oversamples it so that the model has examples to learn from.",
            "oversampling_factor": float(y.mean() / (config.REAL_FRAUD_INCIDENTS_FY25 / config.REAL_UPI_TRANSACTIONS_FY25)),
        },
        "systems": systems,
        "policy": {"bands": bundle["bands"], "budgets": BUDGETS, "test": actions},
        "layers": layers,
        "leave_one_scam_out": loo,
        "careful_scammers_world": {"stealth_share": STEALTH_WORLD.stealth, "payments": int(len(drift)), "scams": int(drift["label"].sum()), "actions": drift_actions},
        "false_alarms_by_group": groups,
        "real_world_correction": {"flagged": correction, "stopped": correction_stop, "blocked": correction_block},
        "likely_type_accuracy": guess_right,
        "top_features": [{"feature": k, "share_of_gain": v / total} for k, v in sorted(gain.items(), key=lambda x: -x[1])[:12]],
        "anomaly": {"start_percentile": ANOMALY_START, "full_percentile": ANOMALY_FULL, "max_weight": ANOMALY_MAX_WEIGHT},
        "xgb_params": {k: v for k, v in XGB_PARAMS.items()},
    }
    old = json.loads(config.METRICS_FILE.read_text(encoding="utf-8")) if config.METRICS_FILE.exists() else {}
    for keep in ("paysim", "latency"):      # written by their own scripts
        if keep in old:
            metrics[keep] = old[keep]
    config.METRICS_FILE.write_text(json.dumps(metrics, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Real-world correction, flagged: 1 real scam per {correction['false_alarms_per_real_fraud']:,.0f} false alarms at {correction['per_million']:.1f} scams per million", flush=True)
    print(f"Real-world correction, stopped: 1 real scam per {correction_stop['false_alarms_per_real_fraud']:,.0f} false alarms", flush=True)
    print(f"Wrote {config.METRICS_FILE} in {time.time() - started:.0f} s")


if __name__ == "__main__":
    sys.exit(main("--refresh" in sys.argv))
