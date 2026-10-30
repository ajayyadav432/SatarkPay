"""The two trained models and how their opinions become one score.

    risk = 1 - (1 - p) x (1 - a) x (1 - r1) x (1 - r2) ...

p is XGBoost's fraud probability, a comes from the Isolation Forest, r are hard rules. It is the formula
SatarkPay: more evidence never lowers the risk. The risk is then placed on the 0-100 scale using bands measured on
validation data, so a level has a known meaning: "High" is about the top 0.2% of genuine payments.
"""
from __future__ import annotations

import json
from functools import lru_cache

import joblib
import numpy as np
import xgboost as xgb

from app import config
from app.payments.features import ANOMALY_FEATURES, FEATURES

# An unusual payment alone earns a warning at most. Chosen on validation data, by leaving each scam type out of training:
# weight 0.15 keeps nearly all the benefit on scams never seen and costs little on known ones (see plan.md, findings).
ANOMALY_START = 0.99    # below this percentile of normal payments the anomaly model says nothing
ANOMALY_MAX_WEIGHT = 0.15
ANOMALY_FULL = 0.9999

# log(1+x) spreads out long tails, so the forest's random splits do not only separate the few largest values.
LOG_FEATURES = {"out_sum_1h", "payer_unique_in_24h", "payee_unique_in_24h", "amt_vs_median", "amt_vs_max", "kmph", "payee_age_days",
                "out_count_1h", "new_payees_1h", "device_accounts", "payee_reports_30d"}
_LOG_MASK = np.array([n in LOG_FEATURES for n in ANOMALY_FEATURES])
_ANOMALY_IDX = np.array([FEATURES.index(n) for n in ANOMALY_FEATURES])


def anomaly_matrix(X: np.ndarray, medians: np.ndarray) -> np.ndarray:
    """From the full feature matrix to what the forest reads: missing values filled, long tails compressed."""
    A = X[:, _ANOMALY_IDX].astype(np.float64)
    A = np.where(np.isnan(A), medians, A)
    A[:, _LOG_MASK] = np.log1p(np.clip(A[:, _LOG_MASK], 0, None))
    return A


class FastForest:
    """Isolation Forest for one payment at a time. scikit-learn's own call takes milliseconds per row, because it is
    built for batches; this walks all trees at once with the same numbers (checked in tests/test_models.py)."""

    def __init__(self, forest):
        offsets, left, right, feature, threshold, length = [], [], [], [], [], []
        at = 0
        for tree, used, depth, avg in zip(forest.estimators_, forest.estimators_features_, forest._decision_path_lengths, forest._average_path_length_per_tree):
            t = tree.tree_
            offsets.append(at)
            is_leaf = t.children_left == -1
            left.append(np.where(is_leaf, -1, t.children_left + at))
            right.append(np.where(is_leaf, -1, t.children_right + at))
            # Each tree sees only a subset of the features, and numbers them within that subset.
            feature.append(np.where(is_leaf, -1, np.asarray(used)[np.maximum(t.feature, 0)]))
            threshold.append(t.threshold)
            length.append(depth + avg - 1.0)
            at += t.node_count
        self.roots = np.array(offsets)
        self.left, self.right = np.concatenate(left), np.concatenate(right)
        self.feature, self.threshold = np.concatenate(feature), np.concatenate(threshold)
        self.length = np.concatenate(length)
        from sklearn.ensemble._iforest import _average_path_length
        self.denominator = len(forest.estimators_) * _average_path_length([forest._max_samples])[0]

    def score_one(self, x: np.ndarray) -> float:
        """The same value as forest.score_samples for one row: closer to -1 is more unusual."""
        nodes = self.roots.copy()
        active = self.left[nodes] != -1
        while active.any():
            current = nodes[active]
            go_left = x[self.feature[current]] <= self.threshold[current]
            nodes[active] = np.where(go_left, self.left[current], self.right[current])
            active = self.left[nodes] != -1
        return float(-(2.0 ** (-self.length[nodes].sum() / self.denominator)))


def anomaly_percentile(scores, quantiles: np.ndarray):
    """Share of normal training payments that were less unusual than this one."""
    return np.searchsorted(quantiles, -np.asarray(scores), side="right") / len(quantiles)


def anomaly_weight(pct):
    """0 up to the 99th percentile of normal payments, rising to the maximum at the 99.99th."""
    pct = np.asarray(pct, dtype=float)
    return np.clip((pct - ANOMALY_START) / (ANOMALY_FULL - ANOMALY_START), 0.0, 1.0) * ANOMALY_MAX_WEIGHT


def fuse(p, anomaly_w, rule_w):
    """The formula at the top of this file. Works on single values and on whole arrays."""
    return 1.0 - (1.0 - p) * (1.0 - anomaly_w) * (1.0 - rule_w)


class Bands:
    """Risk to the 0-100 scale. The knots are risks measured on genuine validation payments."""

    def __init__(self, knots: dict):
        self.knots = knots
        self.xp = [0.0, knots["low"], knots["medium"], knots["high"], knots["critical"], 1.0]
        self.fp = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]

    def score(self, risk):
        return np.interp(risk, self.xp, self.fp)


class Ensemble:
    """Everything needed at scoring time, loaded once."""

    def __init__(self):
        self.bundle = json.loads(config.BUNDLE_FILE.read_text(encoding="utf-8"))
        self.booster = xgb.Booster()
        self.booster.load_model(config.XGB_FILE)
        self.booster.set_param({"nthread": 1})      # a single row: threads only add overhead
        self.forest = joblib.load(config.IFOREST_FILE)
        self.fast = FastForest(self.forest)
        self.medians = np.array(self.bundle["anomaly_medians"], dtype=np.float64)
        self.quantiles = np.array(self.bundle["anomaly_quantiles"], dtype=np.float64)
        self.bands = Bands(self.bundle["bands"])
        self.normal = self.bundle["normal_ranges"]
        assert self.bundle["features"] == FEATURES, "models/ was trained on other features: run ./run.sh train"

    def probability(self, x: np.ndarray) -> float:
        return float(self.booster.inplace_predict(x.reshape(1, -1), validate_features=False)[0])

    def anomaly(self, x: np.ndarray) -> tuple[float, float]:
        """(percentile among normal payments, weight in the risk)."""
        a = anomaly_matrix(x.reshape(1, -1), self.medians)[0]
        pct = float(anomaly_percentile(self.fast.score_one(a), self.quantiles))
        return pct, float(anomaly_weight(pct))

    def shap_values(self, x: np.ndarray) -> tuple[np.ndarray, float]:
        """Exact TreeSHAP in log-odds: base value + sum(values) = the model's output."""
        contrib = self.booster.predict(xgb.DMatrix(x.reshape(1, -1), feature_names=FEATURES), pred_contribs=True)[0]
        return contrib[:-1], float(contrib[-1])


@lru_cache(maxsize=1)
def ensemble() -> Ensemble:
    return Ensemble()


def ready() -> bool:
    return config.XGB_FILE.exists() and config.IFOREST_FILE.exists() and config.BUNDLE_FILE.exists()
