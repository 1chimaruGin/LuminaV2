"""
Phase 3 v2: Train ML model with GoPlus + trade-derived features.

Trade features are available for ALL tokens (not just 0.7% with GoPlus).
This should dramatically improve model performance.

Usage:
    python ml/train_model_v2.py
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


# ── Feature definitions ──
# GoPlus features (available for ~0.7% of tokens)
GOPLUS_FEATURES = [
    "is_open_source", "is_proxy", "is_honeypot",
    "buy_tax", "sell_tax", "is_mintable", "has_blacklist",
    "can_take_ownership", "owner_change_balance", "hidden_owner",
    "selfdestruct", "external_call", "is_renounced",
    "holder_count", "top10_holder_pct", "creator_pct",
    "lp_locked", "lp_lock_pct",
    "honeypot_sim_success", "honeypot_buy_tax", "honeypot_sell_tax",
]

# Derived binary flags
DERIVED_FLAGS = [
    "has_goplus_data",
    "has_honeypot_data",
]

# Trade-derived features (available for ALL tokens)
TRADE_FEATURES = [
    "total_swaps",
    "total_buys",
    "total_sells",
    "buy_sell_ratio",
    "sell_volume_ratio",
    "total_volume_usd",
    "avg_buy_usd",
    "max_buy_usd",
    "kol_buyer_count",
    "dca_ratio",
    "exit_ratio",
    "avg_hold_sec",
    "max_hold_sec",
    "token_active_sec",
    "net_profit_ratio",
]

ALL_FEATURES = GOPLUS_FEATURES + DERIVED_FLAGS + TRADE_FEATURES


def main():
    t0 = time.time()

    # ── Load GoPlus features + labels ──
    logger.info("Loading features and labels from ClickHouse...")
    data = ch_query("""
        SELECT 
            f.token_address,
            f.token_symbol,
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
    logger.info(f"Loaded {len(data)} samples with GoPlus features")

    # ── Load trade features ──
    trade_path = MODEL_DIR / "trade_features.json"
    with open(trade_path) as f:
        trade_features = json.load(f)
    logger.info(f"Loaded trade features for {len(trade_features)} tokens")

    # ── Build feature matrix ──
    logger.info("Building feature matrix...")
    X_rows = []
    y = []
    tokens = []
    labels_full = []

    for row in data:
        token = row["token_address"]
        tf = trade_features.get(token, {})

        features = []

        # GoPlus features
        for col in GOPLUS_FEATURES:
            features.append(float(row.get(col, 0) or 0))

        # Derived flags
        features.append(1.0 if row.get("holder_count", 0) > 0 else 0.0)  # has_goplus_data
        features.append(1.0 if row.get("honeypot_sim_success", 0) > 0 or row.get("honeypot_buy_tax", 0) > 0 else 0.0)  # has_honeypot_data

        # Trade features
        for col in TRADE_FEATURES:
            features.append(float(tf.get(col, 0) or 0))

        X_rows.append(features)
        y.append(row["is_profitable"])
        tokens.append(token)
        labels_full.append(row["label"])

    X = np.array(X_rows, dtype=np.float32)
    y = np.array(y, dtype=np.int32)

    # Handle NaN/Inf
    X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    logger.info(f"Feature matrix: {X.shape} ({len(ALL_FEATURES)} features)")
    logger.info(f"Labels: profitable={sum(y)}, not={len(y)-sum(y)}, rate={sum(y)/len(y)*100:.1f}%")

    label_counts = defaultdict(int)
    for l in labels_full:
        label_counts[l] += 1
    for label in ["WIN_BIG", "WIN", "BREAKEVEN", "LOSS", "RUG"]:
        logger.info(f"  {label}: {label_counts.get(label, 0)}")

    # ── Train/test split ──
    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    logger.info(f"Train: {len(X_train)} | Test: {len(X_test)}")

    # ── Train models ──
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, classification_report

    results = {}

    # XGBoost
    try:
        import xgboost as xgb
        logger.info("\n── Training XGBoost ──")
        pos = sum(y_train)
        neg = len(y_train) - pos
        xgb_model = xgb.XGBClassifier(
            n_estimators=500, max_depth=7, learning_rate=0.03,
            scale_pos_weight=neg / max(pos, 1),
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
            eval_metric="logloss", random_state=42,
        )
        xgb_model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
        y_pred = xgb_model.predict(X_test)
        y_proba = xgb_model.predict_proba(X_test)[:, 1]
        results["xgboost"] = {
            "acc": accuracy_score(y_test, y_pred),
            "prec": precision_score(y_test, y_pred, zero_division=0),
            "rec": recall_score(y_test, y_pred, zero_division=0),
            "f1": f1_score(y_test, y_pred, zero_division=0),
            "auc": roc_auc_score(y_test, y_proba),
            "model": xgb_model,
        }
        r = results["xgboost"]
        logger.info(f"  Acc={r['acc']:.4f} Prec={r['prec']:.4f} Rec={r['rec']:.4f} F1={r['f1']:.4f} AUC={r['auc']:.4f}")

        # Feature importance
        imp = xgb_model.feature_importances_
        sorted_idx = np.argsort(imp)[::-1]
        logger.info("  Feature Importance (top 20):")
        for i in sorted_idx[:20]:
            logger.info(f"    {ALL_FEATURES[i]:30s}: {imp[i]:.4f}")
    except ImportError:
        pass

    # LightGBM
    try:
        import lightgbm as lgb
        logger.info("\n── Training LightGBM ──")
        lgb_model = lgb.LGBMClassifier(
            n_estimators=500, max_depth=7, learning_rate=0.03,
            is_unbalance=True, subsample=0.8, colsample_bytree=0.8,
            min_child_samples=10, random_state=42, verbose=-1,
        )
        lgb_model.fit(X_train, y_train, eval_set=[(X_test, y_test)])
        y_pred = lgb_model.predict(X_test)
        y_proba = lgb_model.predict_proba(X_test)[:, 1]
        results["lightgbm"] = {
            "acc": accuracy_score(y_test, y_pred),
            "prec": precision_score(y_test, y_pred, zero_division=0),
            "rec": recall_score(y_test, y_pred, zero_division=0),
            "f1": f1_score(y_test, y_pred, zero_division=0),
            "auc": roc_auc_score(y_test, y_proba),
            "model": lgb_model,
        }
        r = results["lightgbm"]
        logger.info(f"  Acc={r['acc']:.4f} Prec={r['prec']:.4f} Rec={r['rec']:.4f} F1={r['f1']:.4f} AUC={r['auc']:.4f}")

        imp_lgb = lgb_model.feature_importances_
        sorted_idx_lgb = np.argsort(imp_lgb)[::-1]
        logger.info("  Feature Importance (top 20):")
        for i in sorted_idx_lgb[:20]:
            logger.info(f"    {ALL_FEATURES[i]:30s}: {imp_lgb[i]}")
    except ImportError:
        pass

    # Gradient Boosting (sklearn)
    from sklearn.ensemble import GradientBoostingClassifier
    logger.info("\n── Training Gradient Boosting ──")
    gb_model = GradientBoostingClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        min_samples_leaf=10, subsample=0.8, random_state=42,
    )
    gb_model.fit(X_train, y_train)
    y_pred = gb_model.predict(X_test)
    y_proba = gb_model.predict_proba(X_test)[:, 1]
    results["gradient_boosting"] = {
        "acc": accuracy_score(y_test, y_pred),
        "prec": precision_score(y_test, y_pred, zero_division=0),
        "rec": recall_score(y_test, y_pred, zero_division=0),
        "f1": f1_score(y_test, y_pred, zero_division=0),
        "auc": roc_auc_score(y_test, y_proba),
        "model": gb_model,
    }
    r = results["gradient_boosting"]
    logger.info(f"  Acc={r['acc']:.4f} Prec={r['prec']:.4f} Rec={r['rec']:.4f} F1={r['f1']:.4f} AUC={r['auc']:.4f}")

    # ── Model comparison ──
    logger.info("\n" + "=" * 70)
    logger.info("MODEL COMPARISON (v2 with trade features)")
    logger.info("=" * 70)
    logger.info(f"{'Model':25s} {'Acc':>8s} {'Prec':>8s} {'Recall':>8s} {'F1':>8s} {'AUC':>8s}")
    logger.info("-" * 70)

    best_name = None
    best_auc = 0
    for name, r in results.items():
        logger.info(f"{name:25s} {r['acc']:8.4f} {r['prec']:8.4f} {r['rec']:8.4f} {r['f1']:8.4f} {r['auc']:8.4f}")
        if r["auc"] > best_auc:
            best_auc = r["auc"]
            best_name = name

    logger.info(f"\nBest: {best_name} (AUC={best_auc:.4f})")

    # ── Classification report for best model ──
    best = results[best_name]
    y_pred_best = best["model"].predict(X_test)
    logger.info(f"\n{classification_report(y_test, y_pred_best, target_names=['NOT_PROFITABLE', 'PROFITABLE'])}")

    # ── Analyze predictions by label ──
    y_proba_best = best["model"].predict_proba(X_test)[:, 1]
    label_test = [labels_full[i] for i in range(len(data)) if i >= len(X_train)]
    # Reconstruct test indices
    from sklearn.model_selection import train_test_split
    _, _, _, _, idx_train, idx_test = train_test_split(
        X, y, np.arange(len(y)), test_size=0.2, random_state=42, stratify=y
    )

    logger.info("\nAverage predicted probability by label:")
    label_probas = defaultdict(list)
    for i, idx in enumerate(idx_test):
        label_probas[labels_full[idx]].append(y_proba_best[i])
    for label in ["WIN_BIG", "WIN", "BREAKEVEN", "LOSS", "RUG"]:
        probas = label_probas.get(label, [])
        if probas:
            avg_p = sum(probas) / len(probas)
            logger.info(f"  {label:12s}: avg_prob={avg_p:.4f} (n={len(probas)})")

    # ── Save model ──
    model_path = MODEL_DIR / "model_v2.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": best["model"],
            "feature_cols": ALL_FEATURES,
            "model_name": best_name,
            "metrics": {k: v for k, v in best.items() if k != "model"},
            "training_samples": len(X_train),
            "test_samples": len(X_test),
            "positive_rate": float(sum(y) / len(y)),
            "version": 2,
        }, f)
    logger.info(f"\nSaved model to {model_path}")

    config = {
        "model_name": best_name,
        "feature_cols": ALL_FEATURES,
        "version": 2,
        "metrics": {k: round(v, 4) for k, v in best.items() if k != "model"},
        "training_samples": len(X_train),
        "test_samples": len(X_test),
        "positive_rate": round(float(sum(y) / len(y)), 4),
        "label_distribution": dict(label_counts),
        "threshold_snipe": 0.55,
        "threshold_snipe_small": 0.45,
    }
    config_path = MODEL_DIR / "model_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    logger.info(f"Saved config to {config_path}")

    elapsed = time.time() - t0
    logger.info(f"\n{'='*70}")
    logger.info(f"PHASE 3 v2 COMPLETE in {elapsed:.1f}s")
    logger.info(f"  Best model: {best_name} (AUC={best_auc:.4f})")
    logger.info(f"  Features: {len(ALL_FEATURES)} ({len(GOPLUS_FEATURES)} GoPlus + {len(DERIVED_FLAGS)} flags + {len(TRADE_FEATURES)} trade)")
    logger.info(f"  Samples: {len(data)}")
    logger.info(f"{'='*70}")


if __name__ == "__main__":
    main()
