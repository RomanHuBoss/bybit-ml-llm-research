from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from .backtest_background import background_backtester
from .bybit_client import sync_candles, sync_funding, sync_market_bundle, sync_open_interest
from .concurrency import bounded_worker_count
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


def train_due_ml_models(*args, **kwargs):
    # sklearn/joblib подтягиваются только когда фоновый цикл реально дошел до ML-стадии.
    # Это сохраняет быстрый старт API и одновременно убирает ручную обязанность
    # обучать модель по каждому символу.
    from .ml import train_due_models as impl

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
                "market_sync_workers": settings.market_sync_workers,
                "signal_build_workers": settings.signal_build_workers,
                "ml_auto_train": {
                    "enabled": settings.ml_auto_train_enabled,
                    "ttl_hours": settings.ml_auto_train_ttl_hours,
                    "horizon_bars": settings.ml_auto_train_horizon_bars,
                    "max_models_per_cycle": settings.ml_auto_train_max_models_per_cycle,
                    "failure_cooldown_hours": settings.ml_auto_train_failure_cooldown_hours,
                },
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
            market_jobs: list[tuple[str, str]] = []
            for symbol in symbols:
                item: dict[str, Any] = {"symbol": symbol, "status": "pending", "intervals": {}}
                items_by_symbol[symbol] = item
                summary["items"].append(item)
                for interval in intervals:
                    interval_item: dict[str, Any] = {"interval": interval, "status": "pending", "market_ok": False}
                    item["intervals"][interval] = interval_item
                    market_jobs.append((symbol, interval))

            def run_funding_job(symbol: str) -> tuple[str, int | None, str | None]:
                try:
                    return symbol, sync_funding(category, symbol, settings.signal_auto_sync_days), None
                except Exception as exc:
                    return symbol, None, str(exc)

            # Funding не зависит от таймфрейма: при MTF-режиме его нельзя дергать
            # по одному разу на каждый interval. Сначала синхронизируем funding один
            # раз на symbol, затем параллелим только candles/open-interest по interval.
            market_workers = bounded_worker_count(settings.market_sync_workers, max(len(symbols), len(market_jobs)), default=1, hard_limit=8)
            summary["market_workers"] = market_workers
            if len(intervals) == 1:
                funding_by_symbol: dict[str, int] = {}
                funding_errors: dict[str, str] = {}
            elif market_workers <= 1:
                funding_results = [run_funding_job(symbol) for symbol in symbols]
                funding_by_symbol = {symbol: int(rows or 0) for symbol, rows, error in funding_results if error is None}
                funding_errors = {symbol: str(error) for symbol, _rows, error in funding_results if error is not None}
            else:
                with ThreadPoolExecutor(max_workers=min(market_workers, len(symbols)), thread_name_prefix="signal-funding-sync") as pool:
                    funding_results = [future.result() for future in as_completed([pool.submit(run_funding_job, symbol) for symbol in symbols])]
                funding_by_symbol = {symbol: int(rows or 0) for symbol, rows, error in funding_results if error is None}
                funding_errors = {symbol: str(error) for symbol, _rows, error in funding_results if error is not None}

            for symbol, error in funding_errors.items():
                for interval in intervals:
                    interval_item = items_by_symbol[symbol]["intervals"][interval]
                    interval_item.update({"status": "market_error", "error": error[:500]})
                    summary["failed"] += 1
                    logger.warning("background funding sync failed for %s: %s", symbol, error)

            def run_market_job(job: tuple[str, str]) -> tuple[str, str, dict[str, int] | None, str | None]:
                symbol, interval = job
                try:
                    if len(intervals) == 1:
                        return symbol, interval, sync_market_bundle(category, symbol, interval, settings.signal_auto_sync_days), None
                    funding_rows = funding_by_symbol.get(symbol)
                    if funding_rows is None:
                        return symbol, interval, None, funding_errors.get(symbol, "funding_sync_failed")
                    return symbol, interval, {
                        "candles": sync_candles(category, symbol, interval, settings.signal_auto_sync_days),
                        "funding_rates": funding_rows,
                        "open_interest": sync_open_interest(category, symbol, interval, settings.signal_auto_sync_days),
                    }, None
                except Exception as exc:  # один инструмент/таймфрейм не должен останавливать весь цикл
                    return symbol, interval, None, str(exc)

            effective_market_jobs = [(symbol, interval) for symbol, interval in market_jobs if not funding_errors.get(symbol)]
            if market_workers <= 1:
                market_results = [run_market_job(job) for job in effective_market_jobs]
            else:
                with ThreadPoolExecutor(max_workers=market_workers, thread_name_prefix="signal-market-sync") as pool:
                    futures = [pool.submit(run_market_job, job) for job in effective_market_jobs]
                    market_results = [future.result() for future in as_completed(futures)]

            for symbol, interval, payload, error in market_results:
                interval_item = items_by_symbol[symbol]["intervals"][interval]
                if error is None:
                    interval_item["market"] = payload or {}
                    interval_item["market_ok"] = True
                    summary["market_synced"] += 1
                else:
                    # Нельзя строить новую рекомендацию поверх неудачной синхронизации свечей:
                    # это создает иллюзию свежего сигнала на старом/частичном рынке.
                    interval_item.update({"status": "market_error", "error": error[:500]})
                    summary["failed"] += 1
                    logger.warning("background market sync failed for %s %s: %s", symbol, interval, error)

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

            signal_jobs = [
                (symbol, interval)
                for symbol, item in items_by_symbol.items()
                for interval, interval_item in item["intervals"].items()
                if interval_item.get("market_ok")
            ]

            if settings.ml_auto_train_enabled and signal_jobs:
                try:
                    ml_summary = train_due_ml_models(
                        category,
                        signal_jobs,
                        horizon_bars=settings.ml_auto_train_horizon_bars,
                        ttl_hours=settings.ml_auto_train_ttl_hours,
                        max_models=settings.ml_auto_train_max_models_per_cycle,
                        failure_cooldown_hours=settings.ml_auto_train_failure_cooldown_hours,
                    )
                    summary["ml_auto_train"] = ml_summary
                    for ml_item in ml_summary.get("items", []):
                        symbol = str(ml_item.get("symbol") or "").upper()
                        interval = str(ml_item.get("interval") or "").upper()
                        interval_item = items_by_symbol.get(symbol, {}).get("intervals", {}).get(interval)
                        if interval_item is not None:
                            interval_item["ml_status"] = ml_item.get("status")
                            interval_item["ml_reason"] = ml_item.get("reason")
                            if ml_item.get("error"):
                                interval_item["ml_error"] = str(ml_item.get("error"))[:300]
                    if ml_summary.get("failed"):
                        summary["warnings"].append({
                            "stage": "ml_auto_train",
                            "error": f"{ml_summary.get('failed')} model(s) failed; see ml_auto_train.items",
                        })
                except Exception as exc:
                    message = str(exc)
                    summary["ml_auto_train"] = {"enabled": True, "failed": 1, "fatal_error": message[:500]}
                    summary["warnings"].append({"stage": "ml_auto_train", "error": message[:500]})
                    logger.warning("background ML auto-train failed: %s", message)

            def run_signal_job(job: tuple[str, str]) -> tuple[str, str, int, int, str | None]:
                symbol, interval = job
                try:
                    signals = build_latest_signals(category, symbol, interval)
                    upserted = int(persist_signals(category, symbol, interval, signals) or 0)
                    return symbol, interval, len(signals), upserted, None
                except Exception as exc:
                    return symbol, interval, 0, 0, str(exc)

            signal_workers = bounded_worker_count(settings.signal_build_workers, len(signal_jobs), default=1, hard_limit=8)
            summary["signal_workers"] = signal_workers
            if signal_workers <= 1:
                signal_results = [run_signal_job(job) for job in signal_jobs]
            else:
                with ThreadPoolExecutor(max_workers=signal_workers, thread_name_prefix="signal-build") as pool:
                    futures = [pool.submit(run_signal_job, job) for job in signal_jobs]
                    signal_results = [future.result() for future in as_completed(futures)]

            total_upserted = 0
            for symbol, interval, built, upserted, error in signal_results:
                interval_item = items_by_symbol[symbol]["intervals"][interval]
                if error is None:
                    total_upserted += upserted
                    interval_item.update({"status": "ok", "built": built, "upserted": upserted})
                    summary["signals_built"] += built
                    summary["signals_upserted"] += upserted
                else:
                    interval_item.update({"status": "signal_error", "error": error[:500]})
                    summary["failed"] += 1
                    logger.warning("background signal refresh failed for %s %s: %s", symbol, interval, error)

            for item in items_by_symbol.values():
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
        "market_workers": 0,
        "signal_workers": 0,
        "ml_auto_train": {"enabled": settings.ml_auto_train_enabled, "trained": 0, "fresh": 0, "failed": 0, "skipped_limit": 0, "skipped_failure_cooldown": 0, "items": []},
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
