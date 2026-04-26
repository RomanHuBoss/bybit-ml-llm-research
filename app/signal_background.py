from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from .backtest_background import background_backtester
from .bybit_client import sync_market_bundle
from .config import settings
from .llm_background import background_evaluator
from .symbols import build_universe, latest_universe

logger = logging.getLogger(__name__)




def sync_sentiment_bundle_multi(*args, **kwargs):
    # Market-based sentiment читает feature-frame через pandas; импортируем только
    # когда фоновой цикл реально дошел до sentiment-стадии.
    from .sentiment import sync_sentiment_bundle_multi as impl

    return impl(*args, **kwargs)


def build_latest_signals(*args, **kwargs):
    # Стратегии импортируют pandas/numpy. Держим импорт ленивым, чтобы фоновые
    # статусы и запуск приложения не зависели от тяжелого аналитического стека.
    from .strategies import build_latest_signals as impl

    return impl(*args, **kwargs)


def persist_signals(*args, **kwargs):
    from .strategies import persist_signals as impl

    return impl(*args, **kwargs)


class SignalAutoRefresher:
    """Безопасный фоновый контур обновления рекомендаций.

    Контур не отправляет ордера и не создает торговых ботов. Он только поддерживает
    свежую исследовательскую витрину: обновляет universe/рынок/sentiment, строит
    рекомендации по закрытым свечам и будит фоновые backtest/LLM-проверки.
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
        self._last_cycle: dict[str, Any] = _empty_summary()

    def start(self) -> None:
        if not settings.signal_auto_refresh_enabled:
            return
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._stop_requested = False
            self._run_requested = False
            self._thread = threading.Thread(target=self._loop, name="signal-auto-refresher", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

    def request_run(self) -> None:
        # Ручная кнопка/endpoint только будит фоновый контур. Тяжелая синхронизация
        # остается вне UI-потока и не блокирует оператора.
        with self._condition:
            self._run_requested = True
            self._next_run_at = _iso(_now())
            self._condition.notify_all()

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "enabled": settings.signal_auto_refresh_enabled,
                "running": self._running,
                "thread_alive": bool(self._thread and self._thread.is_alive()),
                "interval_sec": settings.signal_auto_refresh_interval_sec,
                "startup_delay_sec": settings.signal_auto_refresh_startup_delay_sec,
                "max_symbols": settings.signal_auto_max_symbols,
                "sync_days": settings.signal_auto_sync_days,
                "intervals": settings.signal_auto_intervals,
                "refresh_universe": settings.signal_auto_refresh_universe,
                "sync_sentiment": settings.signal_auto_sync_sentiment,
                "last_error": self._last_error,
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "next_run_at": self._next_run_at,
                "cycle_no": self._cycle_no,
                "last_cycle": dict(self._last_cycle),
            }

    def _loop(self) -> None:
        delay = max(0, settings.signal_auto_refresh_startup_delay_sec)
        self._set_next_run(delay)
        with self._condition:
            self._condition.wait_for(lambda: self._stop_requested or self._run_requested, timeout=delay)

        while True:
            with self._condition:
                if self._stop_requested:
                    break
                requested = self._run_requested
                self._run_requested = False

            if requested or settings.signal_auto_refresh_enabled:
                self.run_once()

            self._set_next_run(settings.signal_auto_refresh_interval_sec)
            with self._condition:
                self._condition.wait_for(
                    lambda: self._stop_requested or self._run_requested,
                    timeout=max(1, settings.signal_auto_refresh_interval_sec),
                )

    def _set_next_run(self, seconds: int | float) -> None:
        target = datetime.fromtimestamp(_now().timestamp() + max(0, float(seconds)), tz=timezone.utc)
        with self._condition:
            self._next_run_at = _iso(target)

    def run_once(self) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            # Перекрывающиеся циклы опасны: один поток может читать полусвежее состояние,
            # пока другой еще пишет свечи/сигналы. Поэтому второй запуск явно пропускается.
            return {**_empty_summary(), "skipped": 1, "reason": "already_running"}

        started = _now()
        summary = _empty_summary()
        try:
            with self._condition:
                self._running = True
                self._last_started_at = _iso(started)
                self._last_error = None
                self._cycle_no += 1

            category = settings.default_category
            intervals = list(settings.signal_auto_intervals)
            symbols, source = select_auto_symbols(category)
            summary["symbol_source"] = source
            summary["symbols"] = symbols
            summary["intervals"] = intervals
            summary["queued"] = len(symbols) * len(intervals)

            if not symbols:
                summary["skipped"] = 1
                summary["reason"] = "no_symbols"
                return summary

            items_by_symbol: dict[str, dict[str, Any]] = {}
            for symbol in symbols:
                item: dict[str, Any] = {"symbol": symbol, "status": "pending", "intervals": {}}
                items_by_symbol[symbol] = item
                summary["items"].append(item)
                for interval in intervals:
                    interval_item: dict[str, Any] = {"interval": interval, "status": "pending", "market_ok": False}
                    item["intervals"][interval] = interval_item
                    try:
                        interval_item["market"] = sync_market_bundle(category, symbol, interval, settings.signal_auto_sync_days)
                        interval_item["market_ok"] = True
                        summary["market_synced"] += 1
                    except Exception as exc:
                        # Нельзя строить новую рекомендацию поверх неудачной синхронизации свечей:
                        # это создает иллюзию свежего сигнала на старом/частичном рынке.
                        message = str(exc)
                        interval_item.update({"status": "market_error", "error": message[:500]})
                        summary["failed"] += 1
                        logger.warning("background market sync failed for %s %s: %s", symbol, interval, message)

            if settings.signal_auto_sync_sentiment:
                try:
                    # Sentiment синхронизируется после рынка: market-based sentiment должен
                    # видеть свежие свечи каждого таймфрейма, а не предыдущий snapshot 1h.
                    sentiment = sync_sentiment_bundle_multi(symbols, settings.sentiment_lookback_days, intervals, False, category)
                    summary["sentiment"] = sentiment
                except Exception as exc:
                    # Sentiment полезен, но не должен блокировать закрытые рыночные сигналы.
                    message = str(exc)
                    summary["warnings"].append({"stage": "sentiment", "error": message[:500]})
                    logger.warning("background sentiment sync failed: %s", message)

            total_upserted = 0
            for symbol, item in items_by_symbol.items():
                for interval, interval_item in item["intervals"].items():
                    if not interval_item.get("market_ok"):
                        continue
                    try:
                        signals = build_latest_signals(category, symbol, interval)
                        upserted = int(persist_signals(category, symbol, interval, signals) or 0)
                        total_upserted += upserted
                        interval_item.update({"status": "ok", "built": len(signals), "upserted": upserted})
                        summary["signals_built"] += len(signals)
                        summary["signals_upserted"] += upserted
                    except Exception as exc:
                        message = str(exc)
                        interval_item.update({"status": "signal_error", "error": message[:500]})
                        summary["failed"] += 1
                        logger.warning("background signal refresh failed for %s %s: %s", symbol, interval, message)
                statuses = [payload.get("status") for payload in item["intervals"].values()]
                item["status"] = "ok" if statuses and all(status == "ok" for status in statuses) else "partial"

            if total_upserted > 0:
                if settings.backtest_auto_enabled:
                    background_backtester.request_run()
                    summary["downstream_requested"]["backtest"] = True
                if settings.llm_auto_eval_enabled:
                    background_evaluator.request_run()
                    summary["downstream_requested"]["llm"] = True
        except Exception as exc:
            message = str(exc)
            with self._condition:
                self._last_error = message
            summary["failed"] += 1
            summary["fatal_error"] = message[:500]
            logger.exception("background signal refresh cycle failed")
        finally:
            with self._condition:
                self._running = False
                self._last_finished_at = _iso(_now())
                self._last_cycle = summary
            self._run_lock.release()
        return summary


def _empty_summary() -> dict[str, Any]:
    return {
        "queued": 0,
        "market_synced": 0,
        "signals_built": 0,
        "signals_upserted": 0,
        "skipped": 0,
        "failed": 0,
        "symbol_source": None,
        "symbols": [],
        "intervals": [],
        "warnings": [],
        "items": [],
        "downstream_requested": {"backtest": False, "llm": False},
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def select_auto_symbols(category: str) -> tuple[list[str], str]:
    """Выбирает ограниченный список инструментов для фонового обновления.

    Основной вариант — актуальный liquidity universe. Если Bybit/liquidity временно
    недоступны или universe пуст, используется последний сохраненный universe. Только
    после этого допускается fallback на DEFAULT_SYMBOLS; при включенном
    REQUIRE_LIQUIDITY_FOR_SIGNALS такие символы все равно не дадут рекомендаций без
    валидного liquidity snapshot.
    """

    limit = settings.signal_auto_max_symbols
    if settings.signal_auto_refresh_universe:
        try:
            built = build_universe(category, settings.symbol_mode, limit, refresh=True)
            symbols = [str(s).upper() for s in built.get("symbols", []) if s]
            if symbols:
                return symbols[:limit], "rebuilt_universe"
        except Exception as exc:
            logger.warning("background universe rebuild failed: %s", exc)

    try:
        rows = latest_universe(category, settings.symbol_mode, limit)
        symbols = [str(row["symbol"]).upper() for row in rows if row.get("symbol")]
        if symbols:
            return symbols[:limit], "latest_saved_universe"
    except Exception as exc:
        logger.warning("background latest universe lookup failed: %s", exc)

    return [s.upper() for s in settings.default_symbols[:limit]], "default_symbols_fallback"


signal_refresher = SignalAutoRefresher()
