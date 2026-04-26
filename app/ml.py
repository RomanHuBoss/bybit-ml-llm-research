from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import BASE_DIR
from .db import execute_many_values
from .features import FEATURE_COLUMNS, build_ml_dataset, load_market_frame

MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)


def model_path(category: str, symbol: str, interval: str, horizon_bars: int) -> str:
    safe = f"{category}_{symbol.upper()}_{interval}_{horizon_bars}.joblib".replace("/", "_").replace("\\", "_")
    return str(MODELS_DIR / safe)


def train_model(category: str, symbol: str, interval: str, horizon_bars: int = 12) -> dict[str, Any]:
    X, y, _df = build_ml_dataset(category, symbol, interval, horizon_bars)
    if len(X) < 500:
        raise ValueError("Need at least 500 labeled feature rows. Sync more history first.")
    if y.nunique() < 2:
        raise ValueError("ML target has only one class. Increase history, horizon or volatility diversity before training.")

    split = int(len(X) * 0.78)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]
    if y_train.nunique() < 2:
        raise ValueError("Training window has only one target class. Use longer history or another symbol.")

    pipe = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "model",
                HistGradientBoostingClassifier(
                    max_iter=260,
                    learning_rate=0.035,
                    max_leaf_nodes=31,
                    l2_regularization=0.05,
                    random_state=42,
                ),
            ),
        ]
    )
    pipe.fit(X_train, y_train)
    proba = pipe.predict_proba(X_test)[:, 1]
    pred = (proba >= 0.55).astype(int)

    metrics = {
        "accuracy": float(accuracy_score(y_test, pred)),
        "precision": float(precision_score(y_test, pred, zero_division=0)),
        "recall": float(recall_score(y_test, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, proba)) if len(set(y_test)) > 1 else None,
    }

    try:
        scoring = "roc_auc" if len(set(y_test)) > 1 else "accuracy"
        perm = permutation_importance(pipe, X_test, y_test, n_repeats=8, random_state=42, scoring=scoring)
        importance = {col: float(val) for col, val in zip(FEATURE_COLUMNS, perm.importances_mean)}
        importance = dict(sorted(importance.items(), key=lambda kv: abs(kv[1]), reverse=True))
    except Exception:
        importance = {}

    path = model_path(category, symbol, interval, horizon_bars)
    joblib.dump(pipe, path)

    execute_many_values(
        """
        INSERT INTO model_runs(category, symbol, interval, horizon_bars, model_name, train_rows, test_rows,
                               accuracy, precision_score, recall_score, roc_auc, feature_importance, params)
        VALUES %s
        """,
        [
            (
                category,
                symbol.upper(),
                interval,
                horizon_bars,
                "HistGradientBoostingClassifier",
                len(X_train),
                len(X_test),
                metrics["accuracy"],
                metrics["precision"],
                metrics["recall"],
                metrics["roc_auc"],
                importance,
                {"threshold": 0.55, "model_path": path, "target": "future_ret > rolling_median_atr_pct * 0.35"},
            )
        ],
    )
    return {"model_path": path, "rows": len(X), "train_rows": len(X_train), "test_rows": len(X_test), "metrics": metrics, "feature_importance": importance}


def predict_latest(category: str, symbol: str, interval: str, horizon_bars: int = 12) -> dict[str, Any]:
    path = model_path(category, symbol, interval, horizon_bars)
    if not Path(path).exists():
        raise ValueError("Model file not found. Train ML model first.")
    pipe = joblib.load(path)
    df = load_market_frame(category, symbol, interval, limit=1000)
    if df.empty:
        raise ValueError("No market features available.")
    clean = df.dropna(subset=FEATURE_COLUMNS)
    if clean.empty:
        raise ValueError("No complete feature row available.")
    latest = clean.iloc[-1]
    X = latest[FEATURE_COLUMNS].to_frame().T.fillna(0.0)
    proba = float(pipe.predict_proba(X)[:, 1][0])
    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "horizon_bars": horizon_bars,
        "probability_up": proba,
        "time": str(latest["start_time"]),
        "close": float(latest["close"]),
    }
