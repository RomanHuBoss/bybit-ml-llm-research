from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .db import execute, fetch_all, fetch_one
from .llm import LLMUnavailable, market_brief
from .research import rank_candidates_multi
from .serialization import to_jsonable


LLM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS llm_evaluations (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT REFERENCES signals(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    category TEXT,
    symbol TEXT NOT NULL,
    interval TEXT,
    strategy TEXT,
    direction TEXT,
    model TEXT,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','ok','error','skipped')),
    brief TEXT,
    error TEXT,
    duration_ms INTEGER,
    payload JSONB,
    UNIQUE(signal_id)
);
CREATE INDEX IF NOT EXISTS idx_llm_evaluations_lookup
ON llm_evaluations(status, updated_at DESC, symbol);
CREATE INDEX IF NOT EXISTS idx_llm_evaluations_symbol_time
ON llm_evaluations(symbol, updated_at DESC);
"""


def ensure_llm_schema() -> None:
    # Мягкая миграция для обновления существующих установок: после замены файлов
    # фоновой LLM-оценке не должен требоваться ручной SQL, если базовая schema уже есть.
    # CREATE TABLE не добавляет новые поля в уже существующую таблицу, поэтому
    # ниже явно донакатываем колонки и уникальный ключ, которые нужны ON CONFLICT.
    execute(
        """
        CREATE TABLE IF NOT EXISTS llm_evaluations (
            id BIGSERIAL PRIMARY KEY,
            signal_id BIGINT REFERENCES signals(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            category TEXT,
            symbol TEXT NOT NULL DEFAULT '',
            interval TEXT,
            strategy TEXT,
            direction TEXT,
            model TEXT,
            payload_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            brief TEXT,
            error TEXT,
            duration_ms INTEGER,
            payload JSONB
        )
        """
    )
    migrations = [
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS signal_id BIGINT",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS category TEXT",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS symbol TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS interval TEXT",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS strategy TEXT",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS direction TEXT",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS model TEXT",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS payload_hash TEXT",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS brief TEXT",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS error TEXT",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS duration_ms INTEGER",
        "ALTER TABLE llm_evaluations ADD COLUMN IF NOT EXISTS payload JSONB",
        "UPDATE llm_evaluations SET payload_hash = COALESCE(payload_hash, 'legacy:' || id::text) WHERE payload_hash IS NULL",
        "ALTER TABLE llm_evaluations ALTER COLUMN payload_hash SET NOT NULL",
        "DELETE FROM llm_evaluations a USING llm_evaluations b WHERE a.signal_id IS NOT NULL AND a.signal_id=b.signal_id AND a.id < b.id",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_llm_evaluations_signal_id ON llm_evaluations(signal_id)",
        "CREATE INDEX IF NOT EXISTS idx_llm_evaluations_lookup ON llm_evaluations(status, updated_at DESC, symbol)",
        "CREATE INDEX IF NOT EXISTS idx_llm_evaluations_symbol_time ON llm_evaluations(symbol, updated_at DESC)",
    ]
    for sql in migrations:
        execute(sql)


class LLMBackgroundEvaluator:
    """Фоновый LLM-аналитик: периодически оценивает top-кандидатов и сохраняет вердикты.

    Сервис не торгует, не отправляет ордера и не меняет торговое состояние. Его задача — заранее
    подготовить риск-разбор, чтобы оператор не запускал LLM вручную для каждого инструмента.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._run_lock = threading.Lock()
        self._stop_requested = False
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None
        self._next_run_at: str | None = None
        self._cycle_no = 0
        self._last_cycle: dict[str, Any] = {
            "queued": 0,
            "evaluated": 0,
            "skipped": 0,
            "failed": 0,
        }
        self._running = False
        self._run_requested = False

    def start(self, *, force: bool = False) -> None:
        if not force and not settings.llm_auto_eval_enabled:
            return
        try:
            ensure_llm_schema()
        except Exception as exc:
            # Не валим приложение из-за фонового аналитика. Основной экран должен
            # загрузиться и явно показать ошибку LLM-слоя.
            with self._lock:
                self._last_error = str(exc)
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_requested = False
            self._run_requested = False
            self._thread = threading.Thread(target=self._loop, name="llm-auto-evaluator", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

    def request_run(self) -> None:
        # Ручная команда теперь не делает LLM brief синхронно в UI-потоке, а просит фонового
        # аналитика выполнить ближайший цикл как можно раньше.
        with self._condition:
            self._run_requested = True
            self._next_run_at = _iso(_now())
            self._condition.notify_all()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": settings.llm_auto_eval_enabled,
                "running": self._running,
                "thread_alive": bool(self._thread and self._thread.is_alive()),
                "interval_sec": settings.llm_auto_eval_interval_sec,
                "startup_delay_sec": settings.llm_auto_eval_startup_delay_sec,
                "ttl_minutes": settings.llm_auto_eval_ttl_minutes,
                "max_candidates": settings.llm_auto_eval_max_candidates,
                "workers": settings.llm_auto_eval_workers,
                "model": settings.ollama_model,
                "last_error": self._last_error,
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "next_run_at": self._next_run_at,
                "cycle_no": self._cycle_no,
                "last_cycle": dict(self._last_cycle),
            }

    def _loop(self) -> None:
        delay = max(0, settings.llm_auto_eval_startup_delay_sec)
        self._set_next_run(delay)
        with self._condition:
            self._condition.wait_for(lambda: self._stop_requested or self._run_requested, timeout=delay)

        while True:
            with self._condition:
                if self._stop_requested:
                    break
                requested = self._run_requested
                self._run_requested = False
            if requested or settings.llm_auto_eval_enabled:
                self.run_once()
            self._set_next_run(settings.llm_auto_eval_interval_sec)
            with self._condition:
                self._condition.wait_for(
                    lambda: self._stop_requested or self._run_requested,
                    timeout=max(1, settings.llm_auto_eval_interval_sec),
                )

    def _set_next_run(self, seconds: int | float) -> None:
        target = _now().timestamp() + max(0, float(seconds))
        with self._lock:
            self._next_run_at = _iso(datetime.fromtimestamp(target, tz=timezone.utc))

    def run_once(self) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            # Защита от перекрывающихся ручных и фоновых циклов: один и тот же сигнал
            # не должен одновременно получать несколько LLM-запросов и гонки статусов.
            return {"queued": 0, "evaluated": 0, "skipped": 1, "failed": 0, "reason": "already_running"}
        started = _now()
        summary = {"queued": 0, "evaluated": 0, "skipped": 0, "failed": 0}
        try:
            with self._lock:
                self._running = True
                self._last_started_at = _iso(started)
                self._last_error = None
                self._cycle_no += 1

            candidates = candidates_needing_llm()
            summary["queued"] = len(candidates)
            if candidates:
                max_workers = min(settings.llm_auto_eval_workers, len(candidates))
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="llm-eval") as pool:
                    futures = [pool.submit(evaluate_candidate, candidate) for candidate in candidates]
                    for future in as_completed(futures):
                        result = future.result()
                        if result.get("status") == "ok":
                            summary["evaluated"] += 1
                        elif result.get("status") == "skipped":
                            summary["skipped"] += 1
                        else:
                            summary["failed"] += 1
        except Exception as exc:  # фон не должен валить ASGI-приложение
            with self._lock:
                self._last_error = str(exc)
            summary["failed"] += 1
        finally:
            finished = _now()
            with self._lock:
                self._running = False
                self._last_finished_at = _iso(finished)
                self._last_cycle = summary
            self._run_lock.release()
        return summary


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def payload_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(to_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _brief_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    # Ограничиваем payload тем, что реально нужно LLM для риск-разбора. Это уменьшает шум,
    # ускоряет локальную модель и снижает вероятность галлюцинаций на служебных полях.
    keys = [
        "id",
        "created_at",
        "bar_time",
        "symbol",
        "interval",
        "strategy",
        "direction",
        "confidence",
        "entry",
        "stop_loss",
        "take_profit",
        "sentiment_score",
        "rationale",
        "total_return",
        "max_drawdown",
        "sharpe",
        "win_rate",
        "profit_factor",
        "trades_count",
        "roc_auc",
        "precision_score",
        "recall_score",
        "liquidity_score",
        "spread_pct",
        "turnover_24h",
        "open_interest_value",
        "is_eligible",
        "research_score",
        "research_score_base",
        "mtf_status",
        "mtf_action_class",
        "mtf_score",
        "mtf_veto",
        "mtf_reason",
        "mtf_is_entry_candidate",
        "higher_tf_conflict",
        "bias_conflict",
        "regime_conflict",
        "entry_aligned",
        "bias_aligned",
        "regime_aligned",
        "mtf_entry",
        "mtf_bias",
        "mtf_regime",
        "mtf_entry_interval",
        "mtf_bias_interval",
        "mtf_regime_interval",
    ]
    return {key: candidate.get(key) for key in keys if key in candidate}


def _is_eval_fresh(candidate: dict[str, Any], current_hash: str) -> bool:
    updated = candidate.get("llm_updated_at")
    if not updated or candidate.get("llm_payload_hash") != current_hash:
        return False
    if isinstance(updated, str):
        try:
            updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            return False
    elif isinstance(updated, datetime):
        updated_dt = updated
    else:
        return False
    if updated_dt.tzinfo is None:
        updated_dt = updated_dt.replace(tzinfo=timezone.utc)
    age_sec = (_now() - updated_dt.astimezone(timezone.utc)).total_seconds()
    return age_sec <= settings.llm_auto_eval_ttl_minutes * 60


def candidates_needing_llm() -> list[dict[str, Any]]:
    ranked = rank_candidates_multi(
        settings.default_category,
        settings.signal_auto_intervals,
        limit=max(settings.llm_auto_eval_max_candidates * 3, 12),
    )
    selected: list[dict[str, Any]] = []
    for candidate in ranked:
        if not candidate.get("id"):
            continue
        if settings.mtf_consensus_enabled and str(candidate.get("interval") or "").upper() != settings.mtf_entry_interval:
            continue
        if candidate.get("mtf_status") == "context_only" or candidate.get("mtf_action_class") == "CONTEXT_ONLY" or candidate.get("mtf_is_entry_candidate") is False:
            continue
        if candidate.get("direction") not in {"long", "short"}:
            continue
        payload = _brief_payload(candidate)
        current_hash = payload_hash(payload)
        if _is_eval_fresh(candidate, current_hash):
            continue
        candidate["_llm_payload"] = payload
        candidate["_llm_payload_hash"] = current_hash
        selected.append(candidate)
        if len(selected) >= settings.llm_auto_eval_max_candidates:
            break
    return selected


def evaluate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    signal_id = int(candidate["id"])
    payload = candidate.get("_llm_payload") or _brief_payload(candidate)
    current_hash = candidate.get("_llm_payload_hash") or payload_hash(payload)
    started = _now()
    mark_evaluation_running(candidate, current_hash, payload, started)
    try:
        brief = market_brief(payload)
        finished = _now()
        duration_ms = int((finished - started).total_seconds() * 1000)
        save_evaluation(candidate, current_hash, payload, "ok", brief, None, started, finished, duration_ms)
        return {"signal_id": signal_id, "status": "ok"}
    except LLMUnavailable as exc:
        finished = _now()
        duration_ms = int((finished - started).total_seconds() * 1000)
        save_evaluation(candidate, current_hash, payload, "error", None, str(exc), started, finished, duration_ms)
        return {"signal_id": signal_id, "status": "error", "error": str(exc)}
    except Exception as exc:
        finished = _now()
        duration_ms = int((finished - started).total_seconds() * 1000)
        save_evaluation(candidate, current_hash, payload, "error", None, str(exc), started, finished, duration_ms)
        return {"signal_id": signal_id, "status": "error", "error": str(exc)}


def mark_evaluation_running(candidate: dict[str, Any], current_hash: str, payload: dict[str, Any], started: datetime) -> None:
    save_evaluation(candidate, current_hash, payload, "running", None, None, started, None, None)


def save_evaluation(
    candidate: dict[str, Any],
    current_hash: str,
    payload: dict[str, Any],
    status: str,
    brief: str | None,
    error: str | None,
    started: datetime,
    finished: datetime | None,
    duration_ms: int | None,
) -> None:
    execute(
        """
        INSERT INTO llm_evaluations(
            signal_id, created_at, updated_at, started_at, finished_at,
            category, symbol, interval, strategy, direction, model,
            payload_hash, status, brief, error, duration_ms, payload
        ) VALUES (
            %s, NOW(), NOW(), %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (signal_id) DO UPDATE SET
            updated_at=NOW(), started_at=EXCLUDED.started_at, finished_at=EXCLUDED.finished_at,
            category=EXCLUDED.category, symbol=EXCLUDED.symbol, interval=EXCLUDED.interval,
            strategy=EXCLUDED.strategy, direction=EXCLUDED.direction, model=EXCLUDED.model,
            payload_hash=EXCLUDED.payload_hash, status=EXCLUDED.status,
            brief=COALESCE(EXCLUDED.brief, llm_evaluations.brief),
            error=EXCLUDED.error, duration_ms=EXCLUDED.duration_ms,
            payload=EXCLUDED.payload
        """,
        (
            int(candidate["id"]),
            started,
            finished,
            candidate.get("category") or settings.default_category,
            candidate.get("symbol"),
            candidate.get("interval") or settings.default_interval,
            candidate.get("strategy"),
            candidate.get("direction"),
            settings.ollama_model,
            current_hash,
            status,
            brief,
            error,
            duration_ms,
            to_jsonable(payload),
        ),
    )


def latest_evaluations(limit: int = 100) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT id, signal_id, created_at, updated_at, started_at, finished_at,
               category, symbol, interval, strategy, direction, model, payload_hash,
               status, brief, error, duration_ms
        FROM llm_evaluations
        ORDER BY updated_at DESC
        LIMIT %s
        """,
        (limit,),
    )


def evaluation_summary() -> dict[str, Any]:
    row = fetch_one(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status='ok') AS ok,
            COUNT(*) FILTER (WHERE status='running') AS running,
            COUNT(*) FILTER (WHERE status='error') AS error,
            MAX(updated_at) AS last_updated_at
        FROM llm_evaluations
        """
    )
    return row or {"total": 0, "ok": 0, "running": 0, "error": 0, "last_updated_at": None}


background_evaluator = LLMBackgroundEvaluator()
