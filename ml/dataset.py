"""Turn a simulated world into a table of features and labels, by replaying it through the live feature store."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from app.payments.features import FEATURES, FeatureStore, vector
from ml.simulate import START_TS, World, WorldConfig

DAY = 86400.0


def build(cfg: WorldConfig, verbose: bool = True) -> pd.DataFrame:
    """Replay the world in time order: each payment is scored first and recorded after."""
    started = time.time()
    world = World(cfg)
    store = FeatureStore(world.directory)
    rows, meta = [], []
    while (ev := world.next_event()) is not None:
        if ev["event"] == "txn":
            rows.append(vector(store.features_for(ev)))
            meta.append((ev["txn_id"], ev["ts"], ev["payer"], ev["payee"], ev["kind"], ev["amount"], ev["label"], ev["typology"], ev["tag"], ev.get("stealth", False)))
        store.observe(ev)
        world.commit(ev)
    df = pd.DataFrame(np.array(rows, dtype=np.float32), columns=FEATURES)
    m = pd.DataFrame(meta, columns=["txn_id", "ts", "payer", "payee", "kind", "amount_raw", "label", "typology", "tag", "stealth"])
    df = pd.concat([m, df], axis=1)
    df["day"] = ((df["ts"] - START_TS) // DAY).astype(int)
    if verbose:
        print(f"  seed {cfg.seed}: {len(df):,} payments, {df['label'].sum():,} fraud "
              f"({df['label'].mean():.2%}), {time.time() - started:.0f} s", flush=True)
    return df
