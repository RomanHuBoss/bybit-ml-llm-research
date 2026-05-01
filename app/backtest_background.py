from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from .concurrency import bounded_worker_count
from .config import settings
from .db import fetch_all, fetch_one
from .strategy_quality import refresh_strategy_quality

logger = logging.getLogger(__name__)


BACKTEST_STRATEGIES = (
    "regime_adaptive_combo",
    "donchian_atr_breakout",
    "ema_pullback_trend",
    "bollinger_rsi_reversion",
    "funding_extreme_contrarian",
    "oi_trend_confirmation",
    "volatility_squeeze_breakout",
    "trend_continuation_setup",
    "sentiment_fear_reversal",
    "sentiment_greed_reversal",
)


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
            "workers": 0,
            "items": [],
        }

    def start(self, *, force: bool = False) -> None:
        if not force and not settings.backtest_auto_enabled:
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
                "mode": "strategy_matrix",
                "workers": settings.backtest_auto_workers,
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
            return {"queued": 0, "backtested": 0, "skipped": 1, "failed": 0, "workers": 0, "reason": "already_running", "items": []}

        started = _now()
        summary: dict[str, Any] = {"queued": 0, "backtested": 0, "skipped": 0, "failed": 0, "workers": 0, "items": []}
        try:
            with self._condition:
                self._running = True
                self._last_started_at = _iso(started)
                self._last_error = None
                self._cycle_no += 1

            candidates = candidates_needing_backtest(limit=settings.backtest_auto_max_candidates)
            summary["queued"] = len(candidates)
            summary["mode"] = "strategy_matrix"
            workers = bounded_worker_count(settings.backtest_auto_workers, len(candidates), default=1, hard_limit=4)
            summary["workers"] = workers

            def run_candidate(idx: int, candidate: dict[str, Any]) -> tuple[int, dict[str, Any]]:
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
                except Exception as exc:  # один плохой инструмент не должен останавливать весь цикл
                    message = str(exc)
                    item.update({"status": "error", "error": message[:500]})
                    logger.warning("background backtest failed for %s: %s", item, message)
                return idx, item

            if workers <= 1:
                completed = [run_candidate(idx, candidate) for idx, candidate in enumerate(candidates)]
            else:
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="backtest-auto") as pool:
                    futures = [pool.submit(run_candidate, idx, candidate) for idx, candidate in enumerate(candidates)]
                    completed = [future.result() for future in as_completed(futures)]

            for _, item in sorted(completed, key=lambda pair: pair[0]):
                if item.get("status") == "ok":
                    summary["backtested"] += 1
                else:
                    summary["failed"] += 1
                summary["items"].append(item)
            if summary["backtested"]:
                try:
                    summary["quality_refresh"] = refresh_strategy_quality(limit=max(settings.backtest_auto_max_candidates * 2, 50))
                except Exception as exc:
                    summary["quality_refresh"] = {"error": str(exc)[:500]}
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
    """Return stale/missing strategy-matrix cells, not only fresh live signals.

    The previous implementation only backtested strategies that had just emitted a
    signal. That made the UI look like a recommendation stream with permanently
    weak evidence. The matrix mode qualifies symbol+interval+strategy first; live
    signals can then use that quality row as a hard gate for REVIEW_ENTRY.
    """
    candidate_limit = int(limit or settings.backtest_auto_max_candidates)
    intervals = [str(x).strip().upper() for x in settings.signal_auto_intervals if str(x).strip()]
    configured_symbols = [str(x).strip().upper() for x in settings.core_symbols if str(x).strip()]
    strategies = list(BACKTEST_STRATEGIES)
    # Ensure the quality table exists before the LEFT JOIN below.
    try:
        refresh_strategy_quality(limit=1)
    except Exception:
        # If the DB is unavailable the main query will raise the original DB error.
        pass
    return fetch_all(
        """
        WITH strategy_names AS (
            SELECT unnest(%s::text[]) AS strategy
        ), interval_names AS (
            SELECT unnest(%s::text[]) AS interval
        ), latest_universe_time AS (
            SELECT MAX(selected_at) AS selected_at
            FROM symbol_universe
            WHERE category=%s
        ), universe_symbols AS (
            SELECT u.symbol, MIN(u.rank_no) AS rank_no, 1 AS source_rank
            FROM symbol_universe u
            JOIN latest_universe_time t ON t.selected_at = u.selected_at
            WHERE u.category=%s
            GROUP BY u.symbol
        ), live_signal_symbols AS (
            SELECT symbol, 500 AS rank_no, 2 AS source_rank
            FROM signals
            WHERE category=%s AND created_at >= NOW() - (%s::text || ' hours')::interval
            GROUP BY symbol
        ), configured_symbols AS (
            SELECT unnest(%s::text[]) AS symbol, 900 AS rank_no, 3 AS source_rank
        ), candidate_symbols AS (
            SELECT DISTINCT ON (symbol) symbol, rank_no, source_rank
            FROM (
                SELECT * FROM universe_symbols
                UNION ALL SELECT * FROM live_signal_symbols
                UNION ALL SELECT * FROM configured_symbols
            ) x
            WHERE symbol IS NOT NULL AND symbol <> ''
            ORDER BY symbol, source_rank, rank_no
        ), candle_ok AS (
            SELECT category, symbol, interval, COUNT(*) AS candle_count, MAX(start_time) AS last_candle_at
            FROM candles
            WHERE category=%s AND interval = ANY(%s::text[])
            GROUP BY category, symbol, interval
            HAVING COUNT(*) >= 300
        ), latest_signals AS (
            SELECT DISTINCT ON (category, interval, symbol, strategy)
                   category, interval, symbol, strategy, created_at AS signal_created_at, confidence
            FROM signals
            WHERE category=%s AND created_at >= NOW() - (%s::text || ' hours')::interval
            ORDER BY category, interval, symbol, strategy, created_at DESC
        ), latest_backtests AS (
            SELECT DISTINCT ON (category, interval, symbol, strategy)
                   category, interval, symbol, strategy, id AS run_id, created_at AS backtest_created_at
            FROM backtest_runs
            ORDER BY category, interval, symbol, strategy, created_at DESC
        )
        SELECT %s AS category, i.interval, cs.symbol, st.strategy,
               s.signal_created_at, s.confidence,
               c.candle_count, c.last_candle_at,
               b.run_id, b.backtest_created_at,
               q.quality_status, q.quality_score
        FROM candidate_symbols cs
        CROSS JOIN interval_names i
        CROSS JOIN strategy_names st
        JOIN candle_ok c ON c.category=%s AND c.symbol=cs.symbol AND c.interval=i.interval
        LEFT JOIN latest_signals s ON s.category=%s AND s.symbol=cs.symbol AND s.interval=i.interval AND s.strategy=st.strategy
        LEFT JOIN latest_backtests b ON b.category=%s AND b.symbol=cs.symbol AND b.interval=i.interval AND b.strategy=st.strategy
        LEFT JOIN strategy_quality q ON q.category=%s AND q.symbol=cs.symbol AND q.interval=i.interval AND q.strategy=st.strategy
        WHERE b.run_id IS NULL
           OR b.backtest_created_at < NOW() - (%s::text || ' hours')::interval
           OR (s.signal_created_at IS NOT NULL AND b.backtest_created_at < s.signal_created_at)
        ORDER BY
            CASE q.quality_status WHEN 'APPROVED' THEN 0 WHEN 'WATCHLIST' THEN 1 WHEN 'RESEARCH' THEN 2 WHEN 'REJECTED' THEN 4 ELSE 3 END,
            s.confidence DESC NULLS LAST, cs.source_rank, cs.rank_no, c.last_candle_at DESC, cs.symbol, i.interval, st.strategy
        LIMIT %s
        """,
        (
            strategies,
            intervals,
            settings.default_category,
            settings.default_category,
            settings.default_category,
            settings.max_signal_age_hours,
            configured_symbols,
            settings.default_category,
            intervals,
            settings.default_category,
            settings.max_signal_age_hours,
            settings.default_category,
            settings.default_category,
            settings.default_category,
            settings.default_category,
            settings.default_category,
            settings.backtest_auto_ttl_hours,
            candidate_limit,
        ),
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
