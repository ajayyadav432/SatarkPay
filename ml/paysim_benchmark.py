"""The same recipe on data we did not write: PaySim, a public mobile-money simulation.

    python -m ml.paysim_benchmark

It cannot show fake collects or phishing links, because it has no notes, links or devices. It is here to answer one
question: does the training recipe also hold up on someone else's data? We also check it for shortcuts, as SatarkPay did with
PhiUSIIL. Results are added to models/metrics.json. The data is downloaded to data/raw and never stored in the repo.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score

from app import config

URL = "https://huggingface.co/datasets/theman10/paysim/resolve/main/paysim.csv"
SOURCE = {"name": "PaySim", "paper": "Lopez-Rojas, Elmir, Axelsson: PaySim, a financial mobile money simulator for fraud detection (2016)",
          "mirror": "huggingface.co/datasets/theman10/paysim", "original": "kaggle.com/datasets/ealaxi/paysim1"}
RAW = config.DATA_DIR / "raw" / "paysim"
TRAIN_END_STEP = 500        # hours; the data covers about a month
VAL_END_STEP = 600
PARAMS = {"objective": "binary:logistic", "eval_metric": "aucpr", "tree_method": "hist", "max_depth": 6, "eta": 0.08, "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 5, "lambda": 2.0, "seed": 42}


def download() -> pd.DataFrame:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / "paysim.csv"
    if not path.exists():
        print(f"Downloading PaySim (about 490 MB) from {SOURCE['mirror']}...", flush=True)
        urllib.request.urlretrieve(URL, path)
    return pd.read_csv(path, dtype={"type": "category"})


def recall_at_fpr(y, s, fpr):
    return float((s[y == 1] >= np.quantile(s[y == 0], 1 - fpr)).mean())


def report(y, s) -> dict:
    return {"pr_auc": float(average_precision_score(y, s)), "roc_auc": float(roc_auc_score(y, s)), "recall_at_0.1pct": recall_at_fpr(y, s, 0.001), "recall_at_1pct": recall_at_fpr(y, s, 0.01)}


def features(df: pd.DataFrame, with_balances: bool) -> pd.DataFrame:
    out = pd.DataFrame({"amount": df["amount"], "log_amount": np.log1p(df["amount"]), "hour": df["step"] % 24, "is_transfer": (df["type"] == "TRANSFER").astype(np.int8),
                        "dest_is_merchant": df["nameDest"].str.startswith("M").astype(np.int8)})
    # What a live system can know: how often this destination was used before. Computed in time order, so no peeking.
    out["dest_seen_before"] = df.groupby("nameDest", observed=True).cumcount()
    out["orig_seen_before"] = df.groupby("nameOrig", observed=True).cumcount()
    if with_balances:
        out["old_org"] = df["oldbalanceOrg"]
        out["new_org"] = df["newbalanceOrig"]
        out["old_dest"] = df["oldbalanceDest"]
        out["new_dest"] = df["newbalanceDest"]
        out["org_error"] = df["oldbalanceOrg"] - df["amount"] - df["newbalanceOrig"]
        out["emptied"] = ((df["newbalanceOrig"] == 0) & (df["oldbalanceOrg"] > 0)).astype(np.int8)
    return out


def main() -> None:
    started = time.time()
    df = download().sort_values("step", kind="stable").reset_index(drop=True)
    print(f"{len(df):,} rows, {int(df['isFraud'].sum()):,} fraud", flush=True)
    by_type = df.groupby("type", observed=True)["isFraud"].agg(["sum", "count"])
    fraud_types = {t: int(r["sum"]) for t, r in by_type.iterrows()}
    # Fraud happens only in TRANSFER and CASH_OUT. Other types tell a model nothing, so they are left out.
    df = df[df["type"].isin(["TRANSFER", "CASH_OUT"])].reset_index(drop=True)
    fraud = df[df["isFraud"] == 1]
    finding = {
        "fraud_by_type": fraud_types,
        "fraud_rows_emptying_the_account": float(((fraud["newbalanceOrig"] == 0) & (fraud["oldbalanceOrg"] > 0)).mean()),
        "genuine_rows_emptying_the_account": float(((df["isFraud"] == 0) & (df["newbalanceOrig"] == 0) & (df["oldbalanceOrg"] > 0)).sum() / max((df["isFraud"] == 0).sum(), 1)),
        "fraud_where_amount_equals_balance": float((np.isclose(fraud["amount"], fraud["oldbalanceOrg"])).mean()),
        "genuine_where_amount_equals_balance": float(np.isclose(df.loc[df["isFraud"] == 0, "amount"], df.loc[df["isFraud"] == 0, "oldbalanceOrg"]).mean()),
    }
    print("Shortcut check:", json.dumps(finding, indent=1), flush=True)
    train = df["step"] < TRAIN_END_STEP
    val = (df["step"] >= TRAIN_END_STEP) & (df["step"] < VAL_END_STEP)
    test = df["step"] >= VAL_END_STEP
    y = df["isFraud"].to_numpy()
    results = {"source": SOURCE, "rows_used": int(len(df)), "fraud_used": int(y.sum()), "test_rows": int(test.sum()), "test_fraud": int(y[test.to_numpy()].sum()), "test_fraud_share": float(y[test.to_numpy()].mean()),
               "finding": finding, "split": f"by time: step < {TRAIN_END_STEP} train, < {VAL_END_STEP} validation, the rest test"}
    for name, with_balances in (("without_balance_columns", False), ("with_balance_columns", True)):
        X = features(df, with_balances)
        dtrain = xgb.DMatrix(X[train], label=y[train.to_numpy()])
        dval = xgb.DMatrix(X[val], label=y[val.to_numpy()])
        booster = xgb.train(PARAMS, dtrain, num_boost_round=800, evals=[(dval, "val")], early_stopping_rounds=40, verbose_eval=False)
        s = booster.predict(xgb.DMatrix(X[test]), iteration_range=(0, booster.best_iteration + 1))
        results[name] = report(y[test.to_numpy()], s)
        print(f"XGBoost {name}: {results[name]}", flush=True)
    X = features(df, False).to_numpy(dtype=np.float32)
    forest = IsolationForest(n_estimators=100, max_samples=2048, random_state=42, n_jobs=-1).fit(X[train.to_numpy()])
    results["isolation_forest_no_labels"] = report(y[test.to_numpy()], -forest.score_samples(X[test.to_numpy()]))
    print("Isolation Forest:", results["isolation_forest_no_labels"], flush=True)
    results["seconds"] = round(time.time() - started)
    metrics = json.loads(config.METRICS_FILE.read_text(encoding="utf-8")) if config.METRICS_FILE.exists() else {}
    metrics["paysim"] = results
    config.METRICS_FILE.write_text(json.dumps(metrics, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Added to {config.METRICS_FILE} in {results['seconds']} s")


if __name__ == "__main__":
    main()
