"""
Phase 3 v3: Train ML model with ONLY entry-time features (no data leakage).

At snipe time, we can know:
- GoPlus security features (static, available via API)
- KOL consensus (how many tracked wallets bought this token)
- First buy size (from our tracking)
- Token contract properties

We CANNOT know at entry time:
- sell_volume_ratio (requires sells to happen)
- net_profit_ratio (requires outcome)
- avg_hold_sec (requires exit)
- exit_ratio (requires exit)

Usage:
    python ml/train_model_v3.py
"""

import json
import subprocess
import logging
import pickle
import time
from pathlib import Path
from collections import defaultdict

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLICKHOUSE_BIN = str(PROJECT_ROOT / "clickhouse-bin")
MODEL_DIR = PROJECT_ROOT / "ml"


def ch_query(query: str) -> list[dict]:
    cmd = [CLICKHOUSE_BIN, "client", "--query", f"{query} FORMAT JSONEachRow"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.error(f"CH error: {result.stderr[:500]}")
        return []
    rows = []
    for line in result.stdout.strip().split("\n"):
        if line:
            rows.append(json.loads(line))
    return rows


# ── ENTRY-TIME FEATURES ONLY ──
# These are features we can compute BEFORE deciding to snipe

# GoPlus security (static, available at any time via API)
GOPLUS_FEATURES = [
    "is_open_source", "is_proxy", "is_honeypot",
    "buy_tax", "sell_tax", "is_mintable", "has_blacklist",
    "can_take_ownership", "owner_change_balance", "hidden_owner",
    "selfdestruct", "external_call", "is_renounced",
    "holder_count", "top10_holder_pct", "creator_pct",
    "lp_locked", "lp_lock_pct",
    "honeypot_sim_success", "honeypot_buy_tax", "honeypot_sell_tax",
]

# Data availability flags
DATA_FLAGS = [
    "has_goplus_data",
    "has_honeypot_data",
]

# Entry-time trade features (computed from BUY-SIDE only)
ENTRY_FEATURES = [
    "kol_buyer_count",     # How many KOLs bought (real-time tracking)
    "total_buys",          # Total buy transactions from KOLs
    "avg_buy_usd",         # Average buy size
    "max_buy_usd",         # Largest single buy
    "total_buy_volume_usd", # Total buy volume
    "dca_ratio",           # Fraction of KOLs who DCA'd (multiple buys)
    "buy_sell_ratio",      # Buy/sell ratio at time of entry (early buys vs sells from others)
]

ALL_FEATURES = GOPLUS_FEATURES + DATA_FLAGS + ENTRY_FEATURES


def main():
    t0 = time.time()

    # ── Load GoPlus features + labels ──
    logger.info("Loading features and labels from ClickHouse...")
    data = ch_query("""
        SELECT 
            f.token_address, f.token_symbol,
            f.is_open_source, f.is_proxy, f.is_honeypot,
            f.buy_tax, f.sell_tax, f.is_mintable, f.has_blacklist,
            f.can_take_ownership, f.owner_change_balance, f.hidden_owner,
            f.selfdestruct, f.external_call, f.is_renounced,
            f.holder_count, f.top10_holder_pct, f.creator_pct,
            f.lp_locked, f.lp_lock_pct,
            f.honeypot_sim_success, f.honeypot_buy_tax, f.honeypot_sell_tax,
            f.kol_buyer_count,
            l.label, l.is_profitable, l.avg_pnl_pct, l.total_kol_buyers
        FROM lumina.token_features f
        INNER JOIN lumina.token_labels l ON f.token_address = l.token_address
    """)
    logger.info(f"Loaded {len(data)} samples")

    # ── Load trade features (buy-side only) ──
    trade_path = MODEL_DIR / "trade_features.json"
    with open(trade_path) as f:
        trade_features = json.load(f)

    # ── Build feature matrix (entry-time only) ──
    logger.info("Building ENTRY-TIME feature matrix (no leakage)...")
    X_rows = []
    y = []
    labels_full = []

    for row in data:
        token = row["token_address"]
        tf = trade_features.get(token, {})

        features = []

        # GoPlus features
        for col in GOPLUS_FEATURES:
            features.append(float(row.get(col, 0) or 0))

        # Data flags
        features.append(1.0 if row.get("holder_count", 0) > 0 else 0.0)
        features.append(1.0 if row.get("honeypot_sim_success", 0) > 0 or row.get("honeypot_buy_tax", 0) > 0 else 0.0)

        # Entry-time trade features (BUY-SIDE only, no outcome data)
        features.append(float(tf.get("kol_buyer_count", 0)))
        features.append(float(tf.get("total_buys", 0)))
        features.append(float(tf.get("avg_buy_usd", 0)))
        features.append(float(tf.get("max_buy_usd", 0)))
        # total_buy_volume = avg_buy * total_buys (approximate)
        features.append(float(tf.get("avg_buy_usd", 0)) * float(tf.get("total_buys", 0)))
        features.append(float(tf.get("dca_ratio", 0)))
        features.append(float(tf.get("buy_sell_ratio", 0)))

        X_rows.append(features)
        y.append(row["is_profitable"])
        labels_full.append(row["label"])

    X = np.array(X_rows, dtype=np.float32)
    y = np.array(y, dtype=np.int32)
    X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    logger.info(f"Feature matrix: {X.shape} ({len(ALL_FEATURES)} entry-time features)")
    logger.info(f"Labels: profitable={sum(y)}, not={len(y)-sum(y)}, rate={sum(y)/len(y)*100:.1f}%")

    label_counts = defaultdict(int)
    for l in labels_full:
        label_counts[l] += 1
    for label in ["WIN_BIG", "WIN", "BREAKEVEN", "LOSS", "RUG"]:
        logger.info(f"  {label}: {label_counts.get(label, 0)}")

    # ── Train/test split ──
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, classification_report

    X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
        X, y, np.arange(len(y)), test_size=0.2, random_state=42, stratify=y
    )
    logger.info(f"Train: {len(X_train)} | Test: {len(X_test)}")

    results = {}

    # ── XGBoost ──
    try:
        import xgboost as xgb
        logger.info("\n── XGBoost ──")
        pos = sum(y_train); neg = len(y_train) - pos
        model = xgb.XGBClassifier(
            n_estimators=500, max_depth=7, learning_rate=0.03,
            scale_pos_weight=neg / max(pos, 1),
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
            eval_metric="logloss", random_state=42,
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
        yp = model.predict(X_test)
        ypr = model.predict_proba(X_test)[:, 1]
        r = {
            "acc": accuracy_score(y_test, yp), "prec": precision_score(y_test, yp, zero_division=0),
            "rec": recall_score(y_test, yp, zero_division=0), "f1": f1_score(y_test, yp, zero_division=0),
            "auc": roc_auc_score(y_test, ypr), "model": model,
        }
        results["xgboost"] = r
        logger.info(f"  Acc={r['acc']:.4f} Prec={r['prec']:.4f} Rec={r['rec']:.4f} F1={r['f1']:.4f} AUC={r['auc']:.4f}")
        imp = model.feature_importances_
        logger.info("  Top features:")
        for i in np.argsort(imp)[::-1][:15]:
            logger.info(f"    {ALL_FEATURES[i]:30s}: {imp[i]:.4f}")
    except ImportError:
        pass

    # ── LightGBM ──
    try:
        import lightgbm as lgb
        logger.info("\n── LightGBM ──")
        model = lgb.LGBMClassifier(
            n_estimators=500, max_depth=7, learning_rate=0.03,
            is_unbalance=True, subsample=0.8, colsample_bytree=0.8,
            min_child_samples=10, random_state=42, verbose=-1,
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)])
        yp = model.predict(X_test)
        ypr = model.predict_proba(X_test)[:, 1]
        r = {
            "acc": accuracy_score(y_test, yp), "prec": precision_score(y_test, yp, zero_division=0),
            "rec": recall_score(y_test, yp, zero_division=0), "f1": f1_score(y_test, yp, zero_division=0),
            "auc": roc_auc_score(y_test, ypr), "model": model,
        }
        results["lightgbm"] = r
        logger.info(f"  Acc={r['acc']:.4f} Prec={r['prec']:.4f} Rec={r['rec']:.4f} F1={r['f1']:.4f} AUC={r['auc']:.4f}")
    except ImportError:
        pass

    # ── Gradient Boosting ──
    from sklearn.ensemble import GradientBoostingClassifier
    logger.info("\n── Gradient Boosting ──")
    model = GradientBoostingClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        min_samples_leaf=10, subsample=0.8, random_state=42,
    )
    model.fit(X_train, y_train)
    yp = model.predict(X_test)
    ypr = model.predict_proba(X_test)[:, 1]
    r = {
        "acc": accuracy_score(y_test, yp), "prec": precision_score(y_test, yp, zero_division=0),
        "rec": recall_score(y_test, yp, zero_division=0), "f1": f1_score(y_test, yp, zero_division=0),
        "auc": roc_auc_score(y_test, ypr), "model": model,
    }
    results["gradient_boosting"] = r
    logger.info(f"  Acc={r['acc']:.4f} Prec={r['prec']:.4f} Rec={r['rec']:.4f} F1={r['f1']:.4f} AUC={r['auc']:.4f}")

    # ── Comparison ──
    logger.info("\n" + "=" * 70)
    logger.info("MODEL COMPARISON v3 (entry-time features only, NO LEAKAGE)")
    logger.info("=" * 70)
    logger.info(f"{'Model':25s} {'Acc':>8s} {'Prec':>8s} {'Recall':>8s} {'F1':>8s} {'AUC':>8s}")
    logger.info("-" * 70)

    best_name = None; best_auc = 0
    for name, r in results.items():
        logger.info(f"{name:25s} {r['acc']:8.4f} {r['prec']:8.4f} {r['rec']:8.4f} {r['f1']:8.4f} {r['auc']:8.4f}")
        if r["auc"] > best_auc:
            best_auc = r["auc"]; best_name = name

    logger.info(f"\nBest: {best_name} (AUC={best_auc:.4f})")

    # Classification report
    best = results[best_name]
    yp_best = best["model"].predict(X_test)
    ypr_best = best["model"].predict_proba(X_test)[:, 1]
    logger.info(f"\n{classification_report(y_test, yp_best, target_names=['NOT_PROFITABLE', 'PROFITABLE'])}")

    # Avg probability by label
    logger.info("Avg predicted probability by label:")
    label_probas = defaultdict(list)
    for i, idx in enumerate(idx_test):
        label_probas[labels_full[idx]].append(ypr_best[i])
    for label in ["WIN_BIG", "WIN", "BREAKEVEN", "LOSS", "RUG"]:
        probas = label_probas.get(label, [])
        if probas:
            logger.info(f"  {label:12s}: avg_prob={sum(probas)/len(probas):.4f} (n={len(probas)})")

    # ── Save ──
    model_path = MODEL_DIR / "model_v3.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": best["model"],
            "feature_cols": ALL_FEATURES,
            "model_name": best_name,
            "metrics": {k: v for k, v in best.items() if k != "model"},
            "training_samples": len(X_train),
            "test_samples": len(X_test),
            "positive_rate": float(sum(y) / len(y)),
            "version": 3,
        }, f)
    logger.info(f"\nSaved to {model_path}")

    config = {
        "model_name": best_name,
        "feature_cols": ALL_FEATURES,
        "version": 3,
        "metrics": {k: round(v, 4) for k, v in best.items() if k != "model"},
        "training_samples": len(X_train),
        "test_samples": len(X_test),
        "positive_rate": round(float(sum(y) / len(y)), 4),
        "label_distribution": dict(label_counts),
        "threshold_snipe": 0.55,
        "threshold_snipe_small": 0.45,
        "note": "Entry-time features only. No data leakage.",
    }
    with open(MODEL_DIR / "model_config.json", "w") as f:
        json.dump(config, f, indent=2)

    elapsed = time.time() - t0
    logger.info(f"\n{'='*70}")
    logger.info(f"PHASE 3 v3 COMPLETE in {elapsed:.1f}s")
    logger.info(f"  Best: {best_name} (AUC={best_auc:.4f})")
    logger.info(f"  Features: {len(ALL_FEATURES)} (entry-time only, no leakage)")
    logger.info(f"  Samples: {len(data)}")
    logger.info(f"{'='*70}")


if __name__ == "__main__":
    main()
