from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .strategy_quality import refresh_strategy_quality


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrategyQualityRefreshService:
    """Фоновый refresh для Strategy Quality Gate.

    Quality refresh может читать сотни backtest-run и тысячи сделок. Его нельзя
    выполнять в HTTP-потоке UI: оператор должен получить быстрый ответ, а экран —
    явный статус фонового пересчета. Сервис сериализует запуски и складывает
    повторный запрос в один pending-run, чтобы кнопка refresh не создавала гонку.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._pending_limit: int | None = None
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._cycle_no = 0

    def request_run(self, limit: int | None = None) -> dict[str, Any]:
        bounded_limit = int(limit or settings.strategy_quality_refresh_limit)
        with self._lock:
            if self._running:
                self._pending_limit = max(self._pending_limit or 0, bounded_limit)
                return {**self.status(), "accepted": True, "queued": True}
            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop,
                args=(bounded_limit,),
                name="strategy-quality-refresh",
                daemon=True,
            )
            self._thread.start()
            return {**self.status(), "accepted": True, "queued": False}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": True,
                "running": self._running,
                "thread_alive": bool(self._thread and self._thread.is_alive()),
                "pending": self._pending_limit is not None,
                "pending_limit": self._pending_limit,
                "default_limit": settings.strategy_quality_refresh_limit,
                "time_budget_sec": settings.strategy_quality_refresh_time_budget_sec,
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "last_error": self._last_error,
                "last_result": dict(self._last_result or {}),
                "cycle_no": self._cycle_no,
            }

    def _run_loop(self, first_limit: int) -> None:
        current_limit: int | None = first_limit
        while current_limit is not None:
            with self._lock:
                self._cycle_no += 1
                self._pending_limit = None
                self._last_error = None
                self._last_started_at = _now_iso()

            try:
                result = refresh_strategy_quality(
                    limit=current_limit,
                    time_budget_sec=settings.strategy_quality_refresh_time_budget_sec,
                )
            except Exception as exc:  # pragma: no cover - зависит от БД и локальной среды.
                result = None
                error = str(exc)[:1000]
            else:
                error = None

            with self._lock:
                if result is not None:
                    self._last_result = result
                self._last_error = error
                self._last_finished_at = _now_iso()
                current_limit = self._pending_limit
                if current_limit is None:
                    self._running = False
                    return


strategy_quality_refresher = StrategyQualityRefreshService()
