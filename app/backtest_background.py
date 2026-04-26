from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .db import fetch_all, fetch_one

logger = logging.getLogger(__name__)


def run_backtest(*args, **kwargs):
    # pandas/numpy-heavy backtest импортируется только перед реальным расчетом.
    # Фоновые статусы и запуск API не должны зависеть от тяжелого аналитического стека.
    from .backtest import run_backtest as impl

    return impl(*args, **kwargs)


class BacktestBackgroundRunner:
    """Фоновый исполнитель backtest для актуальных торговых рекомендаций.

    Сервис не торгует и не меняет рекомендации. Его задача — автоматически поддерживать
    доказательную базу: если по свежему symbol+strategy нет backtest или он устарел,
    backtest пересчитывается с ограниченным лимитом кандидатов и без перекрывающихся циклов.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._run_lock = threading.Lock()
        self._stop_requested = False
        self._run_requested = False
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_error: str | None = None
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None
        self._next_run_at: str | None = None
        self._cycle_no = 0
        self._last_cycle: dict[str, Any] = {
            "queued": 0,
            "backtested": 0,
            "skipped": 0,
            "failed": 0,
            "items": [],
        }

    def start(self) -> None:
        if not settings.backtest_auto_enabled:
            return
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._stop_requested = False
            self._run_requested = False
            self._thread = threading.Thread(target=self._loop, name="backtest-auto-runner", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

    def request_run(self) -> None:
        # Endpoint/построение сигналов только будят фонового исполнителя. Сам backtest остается
        # вне UI-потока, чтобы тяжелый пересчет не блокировал оператора и HTTP-запросы.
        with self._condition:
            self._run_requested = True
            self._next_run_at = _iso(_now())
            self._condition.notify_all()

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "enabled": settings.backtest_auto_enabled,
                "running": self._running,
                "thread_alive": bool(self._thread and self._thread.is_alive()),
                "interval_sec": settings.backtest_auto_interval_sec,
                "startup_delay_sec": settings.backtest_auto_startup_delay_sec,
                "ttl_hours": settings.backtest_auto_ttl_hours,
                "max_candidates": settings.backtest_auto_max_candidates,
                "limit": settings.backtest_auto_limit,
                "last_error": self._last_error,
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "next_run_at": self._next_run_at,
                "cycle_no": self._cycle_no,
                "last_cycle": dict(self._last_cycle),
            }

    def _loop(self) -> None:
        delay = max(0, settings.backtest_auto_startup_delay_sec)
        self._set_next_run(delay)
        with self._condition:
            self._condition.wait_for(lambda: self._stop_requested or self._run_requested, timeout=delay)

        while True:
            with self._condition:
                if self._stop_requested:
                    break
                requested = self._run_requested
                self._run_requested = False

            if requested or settings.backtest_auto_enabled:
                self.run_once()

            self._set_next_run(settings.backtest_auto_interval_sec)
            with self._condition:
                self._condition.wait_for(
                    lambda: self._stop_requested or self._run_requested,
                    timeout=max(1, settings.backtest_auto_interval_sec),
                )

    def _set_next_run(self, seconds: int | float) -> None:
        target = datetime.fromtimestamp(_now().timestamp() + max(0, float(seconds)), tz=timezone.utc)
        with self._condition:
            self._next_run_at = _iso(target)

    def run_once(self) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            # Backtest может быть тяжелым: перекрытие циклов недопустимо, иначе один и тот же
            # symbol+strategy будет конкурировать сам с собой за CPU/БД и портить наблюдаемость.
            return {"queued": 0, "backtested": 0, "skipped": 1, "failed": 0, "reason": "already_running", "items": []}

        started = _now()
        summary: dict[str, Any] = {"queued": 0, "backtested": 0, "skipped": 0, "failed": 0, "items": []}
        try:
            with self._condition:
                self._running = True
                self._last_started_at = _iso(started)
                self._last_error = None
                self._cycle_no += 1

            candidates = candidates_needing_backtest(limit=settings.backtest_auto_max_candidates)
            summary["queued"] = len(candidates)
            for candidate in candidates:
                item = {
                    "category": candidate.get("category"),
                    "symbol": candidate.get("symbol"),
                    "interval": candidate.get("interval"),
                    "strategy": candidate.get("strategy"),
                    "status": "pending",
                }
                try:
                    result = run_backtest(
                        str(candidate["category"]),
                        str(candidate["symbol"]),
                        str(candidate["interval"]),
                        str(candidate["strategy"]),
                        limit=settings.backtest_auto_limit,
                    )
                    item.update({"status": "ok", "run_id": result.get("run_id"), "trades_count": result.get("trades_count")})
                    summary["backtested"] += 1
                except Exception as exc:  # один плохой инструмент не должен останавливать весь цикл
                    message = str(exc)
                    item.update({"status": "error", "error": message[:500]})
                    summary["failed"] += 1
                    logger.warning("background backtest failed for %s: %s", item, message)
                summary["items"].append(item)
        except Exception as exc:
            with self._condition:
                self._last_error = str(exc)
            summary["failed"] += 1
            logger.exception("background backtest cycle failed")
        finally:
            with self._condition:
                self._running = False
                self._last_finished_at = _iso(_now())
                self._last_cycle = summary
            self._run_lock.release()
        return summary


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def candidates_needing_backtest(limit: int | None = None) -> list[dict[str, Any]]:
    candidate_limit = int(limit or settings.backtest_auto_max_candidates)
    return fetch_all(
        """
        WITH latest_signals AS (
            SELECT DISTINCT ON (category, interval, symbol, strategy)
                   category, interval, symbol, strategy, created_at AS signal_created_at, confidence
            FROM signals
            WHERE created_at >= NOW() - (%s::text || ' hours')::interval
              AND (%s = FALSE OR interval = %s)
            ORDER BY category, interval, symbol, strategy, created_at DESC
        ), latest_backtests AS (
            SELECT DISTINCT ON (category, interval, symbol, strategy)
                   category, interval, symbol, strategy, id AS run_id, created_at AS backtest_created_at
            FROM backtest_runs
            ORDER BY category, interval, symbol, strategy, created_at DESC
        )
        SELECT s.category, s.interval, s.symbol, s.strategy,
               s.signal_created_at, s.confidence,
               b.run_id, b.backtest_created_at
        FROM latest_signals s
        LEFT JOIN latest_backtests b
          ON b.category=s.category AND b.interval=s.interval AND b.symbol=s.symbol AND b.strategy=s.strategy
        WHERE b.run_id IS NULL
           OR b.backtest_created_at < s.signal_created_at
           OR b.backtest_created_at < NOW() - (%s::text || ' hours')::interval
        ORDER BY s.confidence DESC NULLS LAST, s.signal_created_at DESC
        LIMIT %s
        """,
        (settings.max_signal_age_hours, settings.mtf_consensus_enabled, settings.mtf_entry_interval, settings.backtest_auto_ttl_hours, candidate_limit),
    )


def backtest_background_summary() -> dict[str, Any]:
    row = fetch_one(
        """
        SELECT COUNT(*) AS total,
               MAX(created_at) AS last_created_at,
               COUNT(*) FILTER (WHERE created_at >= NOW() - (%s::text || ' hours')::interval) AS fresh_runs
        FROM backtest_runs
        """,
        (settings.backtest_auto_ttl_hours,),
    )
    return row or {"total": 0, "fresh_runs": 0, "last_created_at": None}


background_backtester = BacktestBackgroundRunner()
