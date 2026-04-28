from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .runtime import configure_runtime_environment

configure_runtime_environment()



class _JoblibProxy:
    """Lazy joblib facade so app.ml can be imported without sklearn/joblib startup cost."""

    def load(self, *args, **kwargs):
        import joblib as _joblib

        return _joblib.load(*args, **kwargs)

    def dump(self, *args, **kwargs):
        import joblib as _joblib

        return _joblib.dump(*args, **kwargs)


joblib = _JoblibProxy()

from .config import BASE_DIR
from .db import execute_many_values, fetch_one
from .feature_schema import FEATURE_COLUMNS

MODELS_DIR = BASE_DIR / "models"

# Process-local guard against hammering a weak VM with the same failing training
# job every signal refresh cycle. Persistent model freshness remains DB+joblib-based;
# this cache only throttles repeated failures such as insufficient history or
# single-class targets until the next cooldown window.
_AUTO_TRAIN_FAILURES: dict[tuple[str, str, str, int], tuple[datetime, str]] = {}


def model_path(category: str, symbol: str, interval: str, horizon_bars: int, *, ensure_dir: bool = False) -> str:
    if ensure_dir:
        # Каталог создается только перед записью модели. Импорт app.ml не должен
        # требовать прав на запись в корень проекта: это ломает диагностику и тесты
        # в read-only окружениях.
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
    safe = f"{category}_{symbol.upper()}_{interval}_{horizon_bars}.joblib".replace("/", "_").replace("\\", "_")
    return str(MODELS_DIR / safe)


def _to_utc_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def latest_model_run(category: str, symbol: str, interval: str, horizon_bars: int = 12) -> dict[str, Any] | None:
    """Возвращает последнюю запись обучения именно для category+symbol+TF+horizon."""
    return fetch_one(
        """
        SELECT id, created_at, category, symbol, interval, horizon_bars, model_name,
               train_rows, test_rows, accuracy, precision_score, recall_score, roc_auc,
               feature_importance, params
        FROM model_runs
        WHERE category=%s AND symbol=%s AND interval=%s AND horizon_bars=%s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (category, symbol.upper(), interval, horizon_bars),
    )


def model_training_need(category: str, symbol: str, interval: str, horizon_bars: int = 12, ttl_hours: int = 24) -> dict[str, Any]:
    """Диагностирует, требуется ли переобучение модели для конкретного символа.

    Проверяются сразу обе опоры: запись в БД с метриками и файл модели на диске.
    Это важно для переносов проекта между машинами: старая строка model_runs без
    локального joblib-файла не должна выглядеть как готовая ML-модель.
    """
    path = model_path(category, symbol, interval, horizon_bars)
    row = latest_model_run(category, symbol, interval, horizon_bars)
    if row is None:
        return {"needed": True, "reason": "missing_model_run", "model_path": path}
    if not Path(path).exists():
        return {"needed": True, "reason": "missing_model_file", "model_path": path, "latest_run": row}
    created_at = _to_utc_datetime(row.get("created_at"))
    if created_at is None:
        return {"needed": True, "reason": "invalid_model_timestamp", "model_path": path, "latest_run": row}
    age = datetime.now(timezone.utc) - created_at
    if age > timedelta(hours=max(1, int(ttl_hours))):
        return {
            "needed": True,
            "reason": "stale_model_run",
            "age_hours": age.total_seconds() / 3600.0,
            "model_path": path,
            "latest_run": row,
        }
    return {
        "needed": False,
        "reason": "fresh_model",
        "age_hours": age.total_seconds() / 3600.0,
        "model_path": path,
        "latest_run": row,
    }


def train_model(category: str, symbol: str, interval: str, horizon_bars: int = 12) -> dict[str, Any]:
    # Heavy sklearn imports are intentionally inside the training path. Importing
    # app.ml for status checks, API wiring or prediction tests must not initialize
    # the whole sklearn/joblib stack.
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    from .features import build_ml_dataset

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

    path = model_path(category, symbol, interval, horizon_bars, ensure_dir=True)
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
    return {
        "model_path": path,
        "symbol": symbol.upper(),
        "interval": interval,
        "horizon_bars": horizon_bars,
        "rows": len(X),
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "metrics": metrics,
        "feature_importance": importance,
    }


def train_due_models(
    category: str,
    jobs: Iterable[tuple[str, str]],
    *,
    horizon_bars: int = 12,
    ttl_hours: int = 24,
    max_models: int = 2,
    failure_cooldown_hours: int = 6,
) -> dict[str, Any]:
    """Переобучает отсутствующие/устаревшие ML-модели по каждому symbol+TF.

    Функция намеренно последовательная: sklearn-тренировка уже использует числовые
    библиотеки, а фоновый контур одновременно общается с Bybit/PostgreSQL. Так мы
    не создаем непредсказуемую нагрузку на локальную research-машину.
    """
    unique_jobs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for symbol, interval in jobs:
        key = (str(symbol).upper(), str(interval).upper())
        if key not in seen:
            seen.add(key)
            unique_jobs.append(key)

    summary: dict[str, Any] = {
        "enabled": True,
        "horizon_bars": horizon_bars,
        "ttl_hours": ttl_hours,
        "queued": len(unique_jobs),
        "trained": 0,
        "fresh": 0,
        "skipped_limit": 0,
        "skipped_failure_cooldown": 0,
        "failed": 0,
        "items": [],
    }
    trained_attempts = 0
    for symbol, interval in unique_jobs:
        item: dict[str, Any] = {"symbol": symbol, "interval": interval, "status": "pending"}
        summary["items"].append(item)
        try:
            need = model_training_need(category, symbol, interval, horizon_bars, ttl_hours)
            item["reason"] = need.get("reason")
            if not need.get("needed"):
                item.update({"status": "fresh", "age_hours": need.get("age_hours"), "model_path": need.get("model_path")})
                summary["fresh"] += 1
                _AUTO_TRAIN_FAILURES.pop((category, symbol, interval, int(horizon_bars)), None)
                continue

            failure_key = (category, symbol, interval, int(horizon_bars))
            last_failure = _AUTO_TRAIN_FAILURES.get(failure_key)
            if last_failure is not None:
                failed_at, error = last_failure
                cooldown = timedelta(hours=max(1, int(failure_cooldown_hours)))
                remaining = cooldown - (datetime.now(timezone.utc) - failed_at)
                if remaining.total_seconds() > 0:
                    item.update({
                        "status": "skipped_failure_cooldown",
                        "model_path": need.get("model_path"),
                        "last_error": error[:500],
                        "cooldown_remaining_hours": remaining.total_seconds() / 3600.0,
                    })
                    summary["skipped_failure_cooldown"] += 1
                    continue
                _AUTO_TRAIN_FAILURES.pop(failure_key, None)

            if trained_attempts >= max(1, int(max_models)):
                item.update({"status": "skipped_limit", "model_path": need.get("model_path")})
                summary["skipped_limit"] += 1
                continue
            trained_attempts += 1
            result = train_model(category, symbol, interval, horizon_bars)
            _AUTO_TRAIN_FAILURES.pop(failure_key, None)
            item.update({"status": "trained", "result": result})
            summary["trained"] += 1
        except Exception as exc:
            _AUTO_TRAIN_FAILURES[(category, symbol, interval, int(horizon_bars))] = (datetime.now(timezone.utc), str(exc))
            item.update({"status": "failed", "error": str(exc)[:500]})
            summary["failed"] += 1
    return summary


def predict_latest(category: str, symbol: str, interval: str, horizon_bars: int = 12) -> dict[str, Any]:
    from .features import load_market_frame, prepare_feature_matrix

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
    X = prepare_feature_matrix(latest)
    proba_matrix = pipe.predict_proba(X)
    proba = float(proba_matrix[0][1])
    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "horizon_bars": horizon_bars,
        "probability_up": proba,
        "time": str(latest["start_time"]),
        "close": float(latest["close"]),
    }
