"""Train XGBoost and the Isolation Forest on the simulated world and save everything the scorer needs.

    python -m ml.train

Time split: days 0-9 only build up history, 10-30 train, 31-37 validation (early stopping, score bands),
38-44 test. Test scammers are accounts that never appeared as scammers before (ml.evaluate removes the others).
"""
from __future__ import annotations

import json
import sys
import time

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import IsolationForest

from app import config
from app.analysis import models as engine_models
from app.payments.features import ANOMALY_FEATURES, FEATURES
from app.payments.models import anomaly_matrix, anomaly_percentile, anomaly_weight, fuse
from app.payments.rules import combined_rule_weight, rule_hits
from ml.dataset import build
from ml.simulate import WorldConfig

SEED = 42
TRAIN_DAYS = (10, 30)
VAL_DAYS = (31, 37)
TEST_DAYS = (38, 44)
# Share of genuine validation payments allowed at or above each level.
BUDGETS = {"low": 0.05, "medium": 0.01, "high": 0.002, "critical": 0.0005}
UNREPORTED_SHARE = 0.10
CACHE = config.DATA_DIR / "sim"

XGB_PARAMS = {"objective": "binary:logistic", "eval_metric": "aucpr", "tree_method": "hist", "max_depth": 6, "eta": 0.08,
              "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 5, "lambda": 2.0, "seed": SEED}


def world_table(cfg: WorldConfig, name: str, refresh: bool = False) -> pd.DataFrame:
    """Build the table once and keep it: building takes minutes, reading takes seconds."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    df = build(cfg)
    df.to_parquet(path, index=False)
    return df


def split(df: pd.DataFrame, days: tuple[int, int]) -> pd.DataFrame:
    return df[(df["day"] >= days[0]) & (df["day"] <= days[1])]


def with_unreported_scams(df: pd.DataFrame, share: float = UNREPORTED_SHARE) -> pd.DataFrame:
    """Many scams are never reported, so in real training data they look genuine. Testing still uses the true labels."""
    payees = np.sort(df.loc[df["label"] == 1, "payee"].unique())
    hidden = np.random.default_rng(SEED).choice(payees, size=int(len(payees) * share), replace=False)
    return df.assign(label_seen=((df["label"] == 1) & ~df["payee"].isin(hidden)).astype(int))


def fit_xgb(train: pd.DataFrame, val: pd.DataFrame, features=None, rounds=1200, verbose=False) -> xgb.Booster:
    features = features or FEATURES
    dtrain = xgb.DMatrix(train[features], label=train["label_seen"], feature_names=features)
    dval = xgb.DMatrix(val[features], label=val["label_seen"], feature_names=features)
    return xgb.train(XGB_PARAMS, dtrain, num_boost_round=rounds, evals=[(dval, "val")], early_stopping_rounds=50, verbose_eval=100 if verbose else False)


def predict_xgb(booster: xgb.Booster, df: pd.DataFrame, features=None) -> np.ndarray:
    features = features or FEATURES
    return booster.predict(xgb.DMatrix(df[features], feature_names=features), iteration_range=(0, booster.best_iteration + 1))


def fit_forest(train: pd.DataFrame) -> tuple[IsolationForest, np.ndarray, np.ndarray]:
    """No labels are used here. It learns what is common and notices what is not."""
    X = train[FEATURES].to_numpy(dtype=np.float64)
    idx = [FEATURES.index(n) for n in ANOMALY_FEATURES]
    medians = np.nanmedian(X[:, idx], axis=0)
    medians = np.where(np.isnan(medians), 0.0, medians)
    A = anomaly_matrix(X, medians)
    forest = IsolationForest(n_estimators=100, max_samples=2048, max_features=0.75, random_state=SEED, n_jobs=-1).fit(A)
    scores = -forest.score_samples(A)
    quantiles = np.quantile(scores, np.linspace(0, 1, 20001))
    return forest, medians, quantiles


def forest_percentiles(forest, medians, quantiles, df: pd.DataFrame) -> np.ndarray:
    A = anomaly_matrix(df[FEATURES].to_numpy(dtype=np.float64), medians)
    return anomaly_percentile(forest.score_samples(A), quantiles)


def rule_weights(df: pd.DataFrame) -> np.ndarray:
    cols = ["kind_collect", "payee_is_merchant", "payee_verified", "receive_lure", "vpa_risk", "payee_reports_30d", "sms_mentions_payee",
            "link_risk", "link_official", "payee_known"]
    return np.array([combined_rule_weight(rule_hits(*row)) for row in zip(*(df[c].tolist() for c in cols))])


def full_risk(p: np.ndarray, pct: np.ndarray, df: pd.DataFrame) -> np.ndarray:
    return fuse(p, anomaly_weight(pct), rule_weights(df))


def bands_from_validation(risk: np.ndarray, is_genuine: np.ndarray) -> dict:
    genuine = risk[is_genuine]
    knots = {name: float(np.quantile(genuine, 1 - share)) for name, share in BUDGETS.items()}
    # Knots must rise for the 0-100 mapping; many genuine payments share the very lowest risks.
    last = 1e-9
    for name in ("low", "medium", "high", "critical"):
        knots[name] = last = max(knots[name], last + 1e-9)
    return knots


def normal_ranges(train: pd.DataFrame) -> dict:
    """Percentiles of genuine payments, so an explanation can say 'higher than 99% of normal payments'."""
    genuine = train[train["label"] == 0]
    out = {}
    for name in FEATURES:
        v = genuine[name].dropna().to_numpy()
        if len(v):
            out[name] = {"p50": float(np.quantile(v, 0.5)), "p90": float(np.quantile(v, 0.9)), "p99": float(np.quantile(v, 0.99)),
                         "p999": float(np.quantile(v, 0.999))}
    return out


def main(refresh: bool = False) -> None:
    if not all(engine_models.status().values()):
        sys.exit(f"The SatarkPay models were not found in {config.MODELS_DIR}. Training without them would poison the context features.")
    started = time.time()
    print("Building the world...", flush=True)
    df = world_table(WorldConfig(seed=SEED), "world42", refresh)
    df = with_unreported_scams(df)
    train, val = split(df, TRAIN_DAYS), split(df, VAL_DAYS)
    print(f"train {len(train):,} payments ({train['label'].sum():,} fraud), validation {len(val):,} ({val['label'].sum():,} fraud)", flush=True)

    print("Training XGBoost...", flush=True)
    booster = fit_xgb(train, val, verbose=True)
    print(f"  best round {booster.best_iteration}, validation PR-AUC {booster.best_score:.4f}", flush=True)
    booster = booster[: booster.best_iteration + 1]
    booster.best_iteration = booster.num_boosted_rounds() - 1

    print("Training the Isolation Forest (no labels)...", flush=True)
    forest, medians, quantiles = fit_forest(train)

    p_val = predict_xgb(booster, val)
    pct_val = forest_percentiles(forest, medians, quantiles, val)
    risk_val = full_risk(p_val, pct_val, val)
    bands = bands_from_validation(risk_val, val["label_seen"].to_numpy() == 0)

    config.PAY_MODELS_DIR.mkdir(exist_ok=True)
    booster.save_model(config.XGB_FILE)
    joblib.dump(forest, config.IFOREST_FILE, compress=3)
    config.BUNDLE_FILE.write_text(json.dumps({
        "features": FEATURES, "anomaly_features": ANOMALY_FEATURES, "anomaly_medians": medians.tolist(),
        "anomaly_quantiles": quantiles.tolist(), "bands": bands, "budgets": BUDGETS, "normal_ranges": normal_ranges(train),
        "splits": {"train": TRAIN_DAYS, "validation": VAL_DAYS, "test": TEST_DAYS}, "seed": SEED,
    }), encoding="utf-8")
    print(f"Bands: { {k: round(v, 5) for k, v in bands.items()} }")
    print(f"Saved to {config.PAY_MODELS_DIR} in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main("--refresh" in sys.argv)
