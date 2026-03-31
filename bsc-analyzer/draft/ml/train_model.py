"""
Phase 3: Build training dataset from ClickHouse + Train ML model.

Usage:
    python ml/train_model.py

Joins token_features + token_labels → training dataset.
Trains XGBoost/LightGBM model for binary classification (profitable vs not).
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


def ch_insert(table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    data = "\n".join(json.dumps(r) for r in rows) + "\n"
    cmd = [CLICKHOUSE_BIN, "client", "--query", f"INSERT INTO {table} FORMAT JSONEachRow"]
    result = subprocess.run(cmd, input=data, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        logger.error(f"CH insert error: {result.stderr[:500]}")
        return 0
    return len(rows)


# Feature columns for the model
FEATURE_COLS = [
    "is_open_source",
    "is_proxy",
    "is_honeypot",
    "buy_tax",
    "sell_tax",
    "is_mintable",
    "has_blacklist",
    "can_take_ownership",
    "owner_change_balance",
    "hidden_owner",
    "selfdestruct",
    "external_call",
    "is_renounced",
    "holder_count",
    "top10_holder_pct",
    "creator_pct",
    "lp_locked",
    "lp_lock_pct",
    "kol_buyer_count",
    "honeypot_sim_success",
    "honeypot_buy_tax",
    "honeypot_sell_tax",
    "has_goplus_data",       # derived: whether GoPlus returned data
    "has_honeypot_data",     # derived: whether Honeypot.is returned data
]


def main():
    t0 = time.time()

    # ── Step 1: Load features + labels from ClickHouse ──
    logger.info("Loading features and labels from ClickHouse...")

    data = ch_query("""
        SELECT 
            f.token_address,
            f.token_symbol,
            f.is_open_source,
            f.is_proxy,
            f.is_honeypot,
            f.buy_tax,
            f.sell_tax,
            f.is_mintable,
            f.has_blacklist,
            f.can_take_ownership,
            f.owner_change_balance,
            f.hidden_owner,
            f.selfdestruct,
            f.external_call,
            f.is_renounced,
            f.holder_count,
            f.top10_holder_pct,
            f.creator_pct,
            f.lp_locked,
            f.lp_lock_pct,
            f.kol_buyer_count,
            f.honeypot_sim_success,
            f.honeypot_buy_tax,
            f.honeypot_sell_tax,
            l.label,
            l.is_profitable,
            l.avg_pnl_pct,
            l.total_kol_buyers
        FROM lumina.token_features f
        INNER JOIN lumina.token_labels l ON f.token_address = l.token_address
    """)

    logger.info(f"Loaded {len(data)} samples")

    if len(data) < 100:
        logger.error("Not enough data to train. Need at least 100 samples.")
        return

    # ── Step 2: Build feature matrix ──
    logger.info("Building feature matrix...")

    X_rows = []
    y = []
    tokens = []
    labels_full = []

    for row in data:
        features = []
        for col in FEATURE_COLS:
            if col == "has_goplus_data":
                # Token has GoPlus data if holder_count > 0 or is_open_source is set
                features.append(1 if row.get("holder_count", 0) > 0 else 0)
            elif col == "has_honeypot_data":
                features.append(1 if row.get("honeypot_sim_success", 0) > 0 or row.get("honeypot_buy_tax", 0) > 0 or row.get("honeypot_sell_tax", 0) > 0 else 0)
            else:
                features.append(float(row.get(col, 0) or 0))

        X_rows.append(features)
        y.append(row["is_profitable"])
        tokens.append(row["token_address"])
        labels_full.append(row["label"])

    X = np.array(X_rows, dtype=np.float32)
    y = np.array(y, dtype=np.int32)

    logger.info(f"Feature matrix: {X.shape}")
    logger.info(f"Label distribution: profitable={sum(y)}, not_profitable={len(y)-sum(y)}")
    logger.info(f"Positive rate: {sum(y)/len(y)*100:.1f}%")

    # Label distribution
    label_counts = defaultdict(int)
    for l in labels_full:
        label_counts[l] += 1
    for label in ["WIN_BIG", "WIN", "BREAKEVEN", "LOSS", "RUG"]:
        logger.info(f"  {label}: {label_counts.get(label, 0)}")

    # ── Step 3: Train/test split ──
    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
        X, y, np.arange(len(y)), test_size=0.2, random_state=42, stratify=y
    )
    logger.info(f"Train: {len(X_train)} | Test: {len(X_test)}")

    # ── Step 4: Train models ──
    results = {}

    # 4a: XGBoost
    try:
        import xgboost as xgb
        logger.info("\nTraining XGBoost...")

        # Handle class imbalance
        pos_count = sum(y_train)
        neg_count = len(y_train) - pos_count
        scale_pos_weight = neg_count / max(pos_count, 1)

        xgb_model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            scale_pos_weight=scale_pos_weight,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=5,
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=42,
        )
        xgb_model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, classification_report
        y_pred = xgb_model.predict(X_test)
        y_proba = xgb_model.predict_proba(X_test)[:, 1]

        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        auc = roc_auc_score(y_test, y_proba)

        results["xgboost"] = {"acc": acc, "prec": prec, "rec": rec, "f1": f1, "auc": auc, "model": xgb_model}

        logger.info(f"XGBoost Results:")
        logger.info(f"  Accuracy:  {acc:.4f}")
        logger.info(f"  Precision: {prec:.4f}")
        logger.info(f"  Recall:    {rec:.4f}")
        logger.info(f"  F1:        {f1:.4f}")
        logger.info(f"  AUC:       {auc:.4f}")

        # Feature importance
        importances = xgb_model.feature_importances_
        sorted_idx = np.argsort(importances)[::-1]
        logger.info("\nXGBoost Feature Importance (top 15):")
        for i in sorted_idx[:15]:
            logger.info(f"  {FEATURE_COLS[i]:30s}: {importances[i]:.4f}")

        # Classification report
        logger.info(f"\nClassification Report:\n{classification_report(y_test, y_pred, target_names=['NOT_PROFITABLE', 'PROFITABLE'])}")

    except ImportError:
        logger.warning("XGBoost not installed, skipping")

    # 4b: LightGBM
    try:
        import lightgbm as lgb
        logger.info("\nTraining LightGBM...")

        lgb_model = lgb.LGBMClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            is_unbalance=True,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_samples=10,
            random_state=42,
            verbose=-1,
        )
        lgb_model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
        )

        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, classification_report
        y_pred_lgb = lgb_model.predict(X_test)
        y_proba_lgb = lgb_model.predict_proba(X_test)[:, 1]

        acc = accuracy_score(y_test, y_pred_lgb)
        prec = precision_score(y_test, y_pred_lgb, zero_division=0)
        rec = recall_score(y_test, y_pred_lgb, zero_division=0)
        f1 = f1_score(y_test, y_pred_lgb, zero_division=0)
        auc = roc_auc_score(y_test, y_proba_lgb)

        results["lightgbm"] = {"acc": acc, "prec": prec, "rec": rec, "f1": f1, "auc": auc, "model": lgb_model}

        logger.info(f"LightGBM Results:")
        logger.info(f"  Accuracy:  {acc:.4f}")
        logger.info(f"  Precision: {prec:.4f}")
        logger.info(f"  Recall:    {rec:.4f}")
        logger.info(f"  F1:        {f1:.4f}")
        logger.info(f"  AUC:       {auc:.4f}")

        importances_lgb = lgb_model.feature_importances_
        sorted_idx_lgb = np.argsort(importances_lgb)[::-1]
        logger.info("\nLightGBM Feature Importance (top 15):")
        for i in sorted_idx_lgb[:15]:
            logger.info(f"  {FEATURE_COLS[i]:30s}: {importances_lgb[i]}")

    except ImportError:
        logger.warning("LightGBM not installed, skipping")

    # 4c: Random Forest (always available)
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, classification_report

    logger.info("\nTraining Random Forest...")
    rf_model = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_leaf=10,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf_model.fit(X_train, y_train)

    y_pred_rf = rf_model.predict(X_test)
    y_proba_rf = rf_model.predict_proba(X_test)[:, 1]

    acc = accuracy_score(y_test, y_pred_rf)
    prec = precision_score(y_test, y_pred_rf, zero_division=0)
    rec = recall_score(y_test, y_pred_rf, zero_division=0)
    f1 = f1_score(y_test, y_pred_rf, zero_division=0)
    auc = roc_auc_score(y_test, y_proba_rf)

    results["random_forest"] = {"acc": acc, "prec": prec, "rec": rec, "f1": f1, "auc": auc, "model": rf_model}

    logger.info(f"Random Forest Results:")
    logger.info(f"  Accuracy:  {acc:.4f}")
    logger.info(f"  Precision: {prec:.4f}")
    logger.info(f"  Recall:    {rec:.4f}")
    logger.info(f"  F1:        {f1:.4f}")
    logger.info(f"  AUC:       {auc:.4f}")

    # 4d: Gradient Boosting
    logger.info("\nTraining Gradient Boosting...")
    gb_model = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        min_samples_leaf=10,
        subsample=0.8,
        random_state=42,
    )
    gb_model.fit(X_train, y_train)

    y_pred_gb = gb_model.predict(X_test)
    y_proba_gb = gb_model.predict_proba(X_test)[:, 1]

    acc = accuracy_score(y_test, y_pred_gb)
    prec = precision_score(y_test, y_pred_gb, zero_division=0)
    rec = recall_score(y_test, y_pred_gb, zero_division=0)
    f1 = f1_score(y_test, y_pred_gb, zero_division=0)
    auc = roc_auc_score(y_test, y_proba_gb)

    results["gradient_boosting"] = {"acc": acc, "prec": prec, "rec": rec, "f1": f1, "auc": auc, "model": gb_model}

    logger.info(f"Gradient Boosting Results:")
    logger.info(f"  Accuracy:  {acc:.4f}")
    logger.info(f"  Precision: {prec:.4f}")
    logger.info(f"  Recall:    {rec:.4f}")
    logger.info(f"  F1:        {f1:.4f}")
    logger.info(f"  AUC:       {auc:.4f}")

    # ── Step 5: Select best model ──
    logger.info("\n" + "=" * 60)
    logger.info("MODEL COMPARISON")
    logger.info("=" * 60)
    logger.info(f"{'Model':25s} {'Acc':>8s} {'Prec':>8s} {'Recall':>8s} {'F1':>8s} {'AUC':>8s}")
    logger.info("-" * 70)

    best_model_name = None
    best_auc = 0
    for name, r in results.items():
        logger.info(f"{name:25s} {r['acc']:8.4f} {r['prec']:8.4f} {r['rec']:8.4f} {r['f1']:8.4f} {r['auc']:8.4f}")
        if r["auc"] > best_auc:
            best_auc = r["auc"]
            best_model_name = name

    logger.info(f"\nBest model: {best_model_name} (AUC={best_auc:.4f})")

    # ── Step 6: Save best model ──
    best = results[best_model_name]
    model_path = MODEL_DIR / "model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": best["model"],
            "feature_cols": FEATURE_COLS,
            "model_name": best_model_name,
            "metrics": {k: v for k, v in best.items() if k != "model"},
            "training_samples": len(X_train),
            "test_samples": len(X_test),
            "positive_rate": float(sum(y) / len(y)),
        }, f)
    logger.info(f"Saved best model to {model_path}")

    # Save model config
    config = {
        "model_name": best_model_name,
        "feature_cols": FEATURE_COLS,
        "metrics": {k: round(v, 4) for k, v in best.items() if k != "model"},
        "training_samples": len(X_train),
        "test_samples": len(X_test),
        "positive_rate": round(float(sum(y) / len(y)), 4),
        "label_distribution": dict(label_counts),
        "threshold_snipe": 0.60,
        "threshold_snipe_small": 0.50,
    }
    config_path = MODEL_DIR / "model_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    logger.info(f"Saved config to {config_path}")

    # ── Step 7: Insert training dataset into ClickHouse ──
    logger.info("\nInserting training dataset into ClickHouse...")
    training_rows = []
    for i, row in enumerate(data):
        feat_row = X_rows[i]
        training_rows.append({
            "token_address": row["token_address"],
            "token_symbol": row.get("token_symbol", "???"),
            "token_age_at_buy_sec": 0,
            "initial_liq_usd": 0,
            "price_at_entry": 0,
            "is_open_source": int(feat_row[0]),
            "is_proxy": int(feat_row[1]),
            "is_honeypot": int(feat_row[2]),
            "buy_tax": feat_row[3],
            "sell_tax": feat_row[4],
            "is_mintable": int(feat_row[5]),
            "has_blacklist": int(feat_row[6]),
            "can_take_ownership": int(feat_row[7]),
            "owner_change_balance": int(feat_row[8]),
            "hidden_owner": int(feat_row[9]),
            "selfdestruct": int(feat_row[10]),
            "external_call": int(feat_row[11]),
            "is_renounced": int(feat_row[12]),
            "holder_count": int(feat_row[13]),
            "top10_holder_pct": feat_row[14],
            "creator_pct": feat_row[15],
            "lp_locked": int(feat_row[16]),
            "lp_lock_pct": feat_row[17],
            "kol_buyer_count": int(feat_row[18]),
            "honeypot_sim_success": int(feat_row[19]),
            "honeypot_buy_tax": feat_row[20],
            "honeypot_sell_tax": feat_row[21],
            "buy_count_5m": 0,
            "sell_count_5m": 0,
            "unique_buyers_5m": 0,
            "volume_usd_5m": 0,
            "deployer_total_tokens": 0,
            "deployer_rug_count": 0,
            "deployer_avg_lifespan_h": 0,
            "label": labels_full[i],
            "is_profitable": int(y[i]),
            "avg_pnl_pct": float(row.get("avg_pnl_pct", 0)),
        })

    BATCH = 1000
    total = 0
    for i in range(0, len(training_rows), BATCH):
        batch = training_rows[i:i + BATCH]
        total += ch_insert("lumina.training_dataset", batch)
    logger.info(f"Inserted {total} rows into training_dataset")

    elapsed = time.time() - t0
    logger.info(f"\n{'='*60}")
    logger.info(f"PHASE 3 COMPLETE in {elapsed:.1f}s")
    logger.info(f"  Best model: {best_model_name}")
    logger.info(f"  AUC: {best_auc:.4f}")
    logger.info(f"  Training rows: {total}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
