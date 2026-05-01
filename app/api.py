from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from pydantic import BaseModel, Field


class DeferredAPIRouter:
    """Lightweight route recorder that keeps app.api import independent of FastAPI.

    Unit tests and CLI diagnostics often need pure endpoint functions, not ASGI
    registration. Importing FastAPI at this layer made those paths vulnerable to
    third-party import-time failures. `app.main` materializes the real APIRouter
    only when the web server is actually constructed.
    """

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix
        self._routes: list[tuple[str, str, dict[str, Any], Callable[..., Any]]] = []

    def _record(self, method: str, path: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._routes.append((method, path, kwargs, func))
            return func

        return decorator

    def get(self, path: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._record("get", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._record("post", path, **kwargs)

    def build_fastapi_router(self) -> Any:
        from fastapi import APIRouter

        real_router = APIRouter(prefix=self.prefix)
        for method, path, kwargs, func in self._routes:
            getattr(real_router, method)(path, **kwargs)(func)
        return real_router


class HTTPException(Exception):
    """Import-light stand-in that becomes FastAPI's HTTPException when possible."""

    def __new__(cls, status_code: int, detail: Any = None, *args: Any, **kwargs: Any):
        try:
            from fastapi import HTTPException as FastAPIHTTPException

            return FastAPIHTTPException(status_code=status_code, detail=detail, *args, **kwargs)
        except Exception:
            return super().__new__(cls)

    def __init__(self, status_code: int, detail: Any = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

from .backtest_background import background_backtester, backtest_background_summary
from .bybit_client import sync_candles, sync_funding, sync_market_bundle, sync_open_interest
from .concurrency import bounded_worker_count
from .config import settings
from .db import fetch_all, fetch_one
from .llm import LLMUnavailable, market_brief
from .llm_background import background_evaluator, evaluation_summary, latest_evaluations
from .operator_queue import consolidate_operator_queue
from .recommendation import annotate_recommendations
from .research import rank_candidates, rank_candidates_multi
from .safety import annotate_and_filter_fresh_signals
from .signal_background import signal_refresher
from .symbols import build_universe, latest_liquidity, latest_universe, refresh_liquidity
from .strategy_quality import ensure_strategy_quality_storage, latest_strategy_quality, quality_summary, refresh_strategy_quality
from .strategy_quality_background import strategy_quality_refresher
from .strategy_lab import strategy_lab_snapshot, trading_desk_diagnostics
from .validation import bounded_int, normalize_category, normalize_interval, normalize_intervals, normalize_symbol, normalize_symbols

router = DeferredAPIRouter(prefix="/api")

STRATEGY_NAMES = (
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


def _strategy_map():
    # Backtest/strategies подтягивают pandas/numpy; импортируем их только для
    # ручного backtest или построения сигналов, а не при старте всего API.
    from .backtest import STRATEGY_MAP

    return STRATEGY_MAP


def _build_latest_signals(*args, **kwargs):
    from .strategies import build_latest_signals

    return build_latest_signals(*args, **kwargs)


def _persist_signals(*args, **kwargs):
    from .strategies import persist_signals

    return persist_signals(*args, **kwargs)


def _run_backtest(*args, **kwargs):
    from .backtest import run_backtest

    return run_backtest(*args, **kwargs)


def _sync_sentiment_bundle(*args, **kwargs):
    from .sentiment import sync_sentiment_bundle

    return sync_sentiment_bundle(*args, **kwargs)


def _sync_sentiment_bundle_multi(*args, **kwargs):
    from .sentiment import sync_sentiment_bundle_multi

    return sync_sentiment_bundle_multi(*args, **kwargs)


def _apply_mtf_consensus(*args, **kwargs):
    from .mtf import apply_mtf_consensus

    return apply_mtf_consensus(*args, **kwargs)


def _unique_intervals(values: list[str] | tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for value in values:
        interval = str(value).strip().upper()
        if interval and interval not in out:
            out.append(interval)
    return out


def _sentiment_summary(*args, **kwargs):
    from .sentiment import sentiment_summary

    return sentiment_summary(*args, **kwargs)


class MarketSyncRequest(BaseModel):
    category: str = settings.default_category
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols), min_length=1)
    interval: str = settings.default_interval
    intervals: list[str] | None = None
    days: int = Field(default=90, ge=1, le=settings.max_sync_days)


class SentimentSyncRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols), min_length=1)
    days: int = Field(default=settings.sentiment_lookback_days, ge=1, le=60)
    use_llm: bool = False
    category: str = settings.default_category
    interval: str = settings.default_interval
    intervals: list[str] | None = None


class SignalBuildRequest(BaseModel):
    category: str = settings.default_category
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols), min_length=1)
    interval: str = settings.default_interval
    intervals: list[str] | None = None


class BacktestRequest(BaseModel):
    category: str = settings.default_category
    symbol: str = "BTCUSDT"
    interval: str = settings.default_interval
    strategy: str = "donchian_atr_breakout"
    limit: int = Field(default=5000, ge=300, le=100000)


class TrainRequest(BaseModel):
    category: str = settings.default_category
    symbol: str = "BTCUSDT"
    interval: str = settings.default_interval
    horizon_bars: int = Field(default=12, ge=1, le=240)


class BriefRequest(BaseModel):
    signal_id: int | None = None
    payload: dict[str, Any] | None = None


class UniverseRequest(BaseModel):
    category: str = settings.default_category
    mode: str = settings.symbol_mode
    limit: int = Field(default=settings.universe_limit, ge=1, le=100)
    refresh: bool = True


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _read_error(exc: Exception) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _empty_quality_summary() -> dict[str, int]:
    return {"total": 0, "approved": 0, "watchlist": 0, "research": 0, "rejected": 0, "stale": 0}


def _empty_strategy_lab_payload(error: str) -> dict[str, Any]:
    summary = _empty_quality_summary()
    return {
        "summary": {**summary, "status_counts": {"APPROVED": 0, "WATCHLIST": 0, "RESEARCH": 0, "REJECTED": 0, "STALE": 0}},
        "thresholds": {},
        "desk_status": "DEGRADED",
        "headline": f"Strategy Lab недоступна: {error}",
        "blocker_counts": {},
        "trading_desk": [],
        "near_approval": [],
        "rejected": [],
        "items": [],
    }


def _empty_trading_desk_payload(error: str, intervals: list[str] | None = None) -> dict[str, Any]:
    return {
        "intervals": intervals or [],
        "total_candidates": 0,
        "review_entries": 0,
        "desk_status": "DEGRADED",
        "headline": f"Trading Desk diagnostics недоступны: {error}",
        "by_action": {},
        "by_quality": {},
        "blockers": {},
        "items": [],
    }


def _sync_market_interval(category: str, symbol: str, interval: str, days: int, funding_rows: int) -> tuple[str, dict[str, int]]:
    # Funding не зависит от таймфрейма и уже синхронизирован один раз на symbol.
    # Остальные операции независимы по interval и безопасны для ограниченного ThreadPool:
    # каждая запись идет в свою DB-транзакцию, а HTTP-запросы дополнительно ограничены
    # глобальным Bybit semaphore в клиенте.
    return interval, {
        "candles": sync_candles(category, symbol, interval, days),
        "funding_rates": funding_rows,
        "open_interest": sync_open_interest(category, symbol, interval, days),
    }


def _sync_market_bundle_multi(category: str, symbol: str, intervals: list[str], days: int) -> dict[str, dict[str, int]]:
    """Sync multi-timeframe market data without repeating interval-independent funding calls."""
    funding_rows = sync_funding(category, symbol, days)
    workers = bounded_worker_count(settings.market_sync_workers, len(intervals), default=1, hard_limit=8)
    if workers <= 1:
        return dict(_sync_market_interval(category, symbol, interval, days, funding_rows) for interval in intervals)

    result: dict[str, dict[str, int]] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="market-sync-api") as pool:
        futures = [pool.submit(_sync_market_interval, category, symbol, interval, days, funding_rows) for interval in intervals]
        for future in as_completed(futures):
            interval, payload = future.result()
            result[interval] = payload
    return {interval: result[interval] for interval in intervals if interval in result}


@router.get("/status")
def status() -> dict[str, Any]:
    db: dict[str, Any] | None = None
    latest: dict[str, Any] | None = None
    db_error: str | None = None
    try:
        db = fetch_one("SELECT NOW() AS now")
        latest = fetch_one("SELECT COUNT(*) AS candles FROM candles")
    except Exception as exc:
        # /api/status is the first request made by the UI. If PostgreSQL is down or
        # the schema is not initialized yet, the page must still load diagnostics
        # and let the operator use non-DB controls instead of failing with HTTP 500.
        db_error = str(exc)
    return {
        "ok": db_error is None,
        "db_error": db_error,
        "db_time": str(db["now"]) if db else None,
        "candles": int(latest["candles"]) if latest else 0,
        "default_symbols": settings.default_symbols,
        "core_symbols": settings.core_symbols,
        "symbol_mode": settings.symbol_mode,
        "strategies": sorted(set(STRATEGY_NAMES)),
        "risk_controls": {
            "risk_per_trade": settings.risk_per_trade,
            "max_position_notional_usdt": settings.max_position_notional_usdt,
            "max_leverage": settings.max_leverage,
            "require_liquidity_for_signals": settings.require_liquidity_for_signals,
            "liquidity_snapshot_max_age_minutes": settings.liquidity_snapshot_max_age_minutes,
        },
        "max_signal_age_hours": settings.max_signal_age_hours,
        "backtest_auto": {
            "enabled": settings.backtest_auto_enabled,
            "interval_sec": settings.backtest_auto_interval_sec,
            "max_candidates": settings.backtest_auto_max_candidates,
            "limit": settings.backtest_auto_limit,
            "ttl_hours": settings.backtest_auto_ttl_hours,
            "workers": settings.backtest_auto_workers,
            "mode": "strategy_matrix",
        },
        "strategy_quality": {
            "require_approval_for_review": settings.require_strategy_approval_for_review,
            "min_trades": settings.strategy_approval_min_trades,
            "min_profit_factor": settings.strategy_approval_min_profit_factor,
            "max_drawdown": settings.strategy_approval_max_drawdown,
            "min_total_return": settings.strategy_approval_min_total_return,
            "walk_forward_windows": settings.strategy_walk_forward_windows,
            "walk_forward_min_windows": settings.strategy_walk_forward_min_windows,
            "walk_forward_min_pass_rate": settings.strategy_walk_forward_min_pass_rate,
            "require_walk_forward_for_approval": settings.require_walk_forward_for_approval,
            "quality_max_age_days": settings.strategy_quality_max_age_days,
            "min_expectancy": settings.strategy_min_expectancy,
            "min_recent_30d_return": settings.strategy_min_recent_30d_return,
            "refresh_limit": settings.strategy_quality_refresh_limit,
            "refresh_time_budget_sec": settings.strategy_quality_refresh_time_budget_sec,
            "refresh_background": strategy_quality_refresher.status(),
        },
        "mtf_consensus": {
            "enabled": settings.mtf_consensus_enabled,
            "entry_interval": settings.mtf_entry_interval,
            "bias_interval": settings.mtf_bias_interval,
            "regime_interval": settings.mtf_regime_interval,
        },
        "signal_auto_refresh": {
            "enabled": settings.signal_auto_refresh_enabled,
            "interval_sec": settings.signal_auto_refresh_interval_sec,
            "max_symbols": settings.signal_auto_max_symbols,
            "sync_days": settings.signal_auto_sync_days,
            "intervals": settings.signal_auto_intervals,
            "sync_sentiment": settings.signal_auto_sync_sentiment,
            "market_sync_workers": settings.market_sync_workers,
            "signal_build_workers": settings.signal_build_workers,
        },
        "ml_auto_train": {
            "enabled": settings.ml_auto_train_enabled,
            "ttl_hours": settings.ml_auto_train_ttl_hours,
            "horizon_bars": settings.ml_auto_train_horizon_bars,
            "max_models_per_cycle": settings.ml_auto_train_max_models_per_cycle,
            "failure_cooldown_hours": settings.ml_auto_train_failure_cooldown_hours,
            "probability_in_signals": settings.ml_probability_in_signals_enabled,
        },
        "sentiment_sources": {
            "fear_greed": settings.use_fear_greed,
            "gdelt": settings.use_gdelt,
            "rss": settings.use_rss,
            "market_microstructure": settings.use_market_sentiment,
            "cryptopanic": bool(settings.use_cryptopanic and settings.cryptopanic_token),
        },
        "live_trading": False,
    }


@router.post("/symbols/liquidity/sync")
def api_refresh_liquidity(category: str = settings.default_category) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        return {"ok": True, "result": refresh_liquidity(category)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/symbols/liquidity/latest")
def api_latest_liquidity(category: str = settings.default_category, limit: int = 50) -> dict[str, Any]:
    try:
        return {"ok": True, "items": latest_liquidity(normalize_category(category), bounded_int(limit, "limit", 1, 500))}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "items": [], "error": _read_error(exc)}


@router.post("/symbols/universe/build")
def api_build_universe(req: UniverseRequest) -> dict[str, Any]:
    try:
        category = normalize_category(req.category)
        mode = req.mode.strip().lower()
        if mode not in {"core", "dynamic", "hybrid"}:
            raise ValueError("mode должен быть core, dynamic или hybrid")
        return {"ok": True, "result": build_universe(category, mode, req.limit, req.refresh)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/symbols/universe/latest")
def api_latest_universe(category: str = settings.default_category, mode: str | None = None, limit: int = 50) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        mode = mode.strip().lower() if mode else None
        if mode and mode not in {"core", "dynamic", "hybrid"}:
            raise ValueError("mode должен быть core, dynamic или hybrid")
        return {"ok": True, "items": latest_universe(category, mode, bounded_int(limit, "limit", 1, 500))}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "items": [], "error": _read_error(exc)}


@router.post("/sync/market")
def sync_market(req: MarketSyncRequest) -> dict[str, Any]:
    result = {}
    try:
        category = normalize_category(req.category)
        intervals = normalize_intervals(req.intervals or req.interval)
        symbols = normalize_symbols(req.symbols)
        days = bounded_int(req.days, "days", 1, settings.max_sync_days)
        for symbol in symbols:
            if len(intervals) == 1:
                result[symbol] = sync_market_bundle(category, symbol, intervals[0], days)
            else:
                result[symbol] = _sync_market_bundle_multi(category, symbol, intervals, days)
        return {"ok": True, "intervals": intervals, "result": result}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sync/sentiment")
def sync_sentiment(req: SentimentSyncRequest) -> dict[str, Any]:
    try:
        category = normalize_category(req.category)
        intervals = normalize_intervals(req.intervals or req.interval)
        symbols = normalize_symbols(req.symbols)
        days = bounded_int(req.days, "days", 1, 60)
        if len(intervals) == 1:
            result = _sync_sentiment_bundle(symbols, days, req.use_llm, category, intervals[0])
        else:
            result = _sync_sentiment_bundle_multi(symbols, days, intervals, req.use_llm, category)
        return {"ok": True, "intervals": intervals, "result": result}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/sentiment/summary")
def api_sentiment_summary(symbol: str = "BTCUSDT", limit: int = 20) -> dict[str, Any]:
    try:
        return {"ok": True, "result": _sentiment_summary(normalize_symbol(symbol), bounded_int(limit, "limit", 1, 200))}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "result": {"score": None, "summary_score": None, "items": []}, "error": _read_error(exc)}


@router.post("/signals/build")
def build_signals(req: SignalBuildRequest) -> dict[str, Any]:
    output: dict[str, Any] = {}
    try:
        category = normalize_category(req.category)
        intervals = normalize_intervals(req.intervals or req.interval)
        symbols = normalize_symbols(req.symbols)
        jobs = [(symbol, interval) for symbol in symbols for interval in intervals]

        def run_job(symbol: str, interval: str) -> tuple[str, str, dict[str, Any], int]:
            # Ручной build не должен искусственно становиться медленнее из-за
            # последовательного обхода symbol×interval. Каждая job использует
            # собственные DB-соединения через app.db, поэтому ограниченный пул потоков
            # безопаснее и наблюдаемее, чем один длинный HTTP-запрос на всю корзину.
            signals = _build_latest_signals(category, symbol, interval)
            inserted = int(_persist_signals(category, symbol, interval, signals) or 0)
            payload = {"built": len(signals), "upserted": inserted, "signals": [s.__dict__ for s in signals]}
            return symbol, interval, payload, inserted

        workers = bounded_worker_count(settings.signal_build_workers, len(jobs), default=1, hard_limit=8)
        if workers <= 1 or len(jobs) <= 1:
            completed = [run_job(symbol, interval) for symbol, interval in jobs]
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="api-signal-build") as pool:
                futures = [pool.submit(run_job, symbol, interval) for symbol, interval in jobs]
                completed = [future.result() for future in as_completed(futures)]

        total_inserted = 0
        for symbol, interval, payload, inserted in sorted(completed, key=lambda item: (symbols.index(item[0]), intervals.index(item[1]))):
            total_inserted += inserted
            if len(intervals) == 1:
                output[symbol] = payload
            else:
                output.setdefault(symbol, {})[interval] = payload
        backtest_requested = False
        llm_requested = False
        if total_inserted > 0:
            if settings.backtest_auto_enabled:
                background_backtester.request_run()
                backtest_requested = True
            if settings.llm_auto_eval_enabled:
                background_evaluator.request_run()
                llm_requested = True
        return {
            "ok": True,
            "intervals": intervals,
            "workers": workers,
            "jobs": len(jobs),
            "result": output,
            "backtest_auto_requested": backtest_requested,
            "llm_auto_requested": llm_requested,
        }
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/signals/background/status")
def api_signal_background_status() -> dict[str, Any]:
    return {"ok": True, "status": signal_refresher.status()}


@router.post("/signals/background/run-now")
def api_signal_background_run_now() -> dict[str, Any]:
    signal_refresher.start(force=True)
    signal_refresher.request_run()
    return {"ok": True, "accepted": True, "status": signal_refresher.status()}


@router.get("/signals/latest")
def latest_signals(limit: int = 50, entry_only: bool = True, category: str = settings.default_category) -> dict[str, Any]:
    try:
        limit = bounded_int(limit, "limit", 1, 500)
        category = normalize_category(category)
    except ValueError as exc:
        raise _bad_request(exc) from exc

    try:
        if settings.mtf_consensus_enabled:
            entry_interval = str(settings.mtf_entry_interval).strip().upper()
            context_intervals = _unique_intervals([settings.mtf_entry_interval, settings.mtf_bias_interval, settings.mtf_regime_interval])
            query_limit = max(limit * 8, 120)
            try:
                # Без этого JOIN /api/signals/latest никогда не видел APPROVED quality-row
                # и классифицировал любой живой сетап как RESEARCH_CANDIDATE. Это был
                # критичный разрыв между витриной оператора и Strategy Quality Gate.
                ensure_strategy_quality_storage()
            except Exception:
                # Если БД/миграция недоступны, основной запрос вернет диагностируемую
                # ошибку. На этом уровне не скрываем отказ от пользователя.
                pass
            rows = fetch_all(
                """
                WITH latest_signals AS (
                    SELECT DISTINCT ON (category, symbol, interval, strategy, direction)
                           id, created_at, bar_time, category, symbol, interval, strategy, direction, confidence,
                           entry, stop_loss, take_profit, atr, ml_probability, sentiment_score, rationale
                    FROM signals
                    WHERE category=%s AND interval = ANY(%s::text[]) AND created_at >= NOW() - (%s::text || ' hours')::interval
                      AND bar_time IS NOT NULL
                    ORDER BY category, symbol, interval, strategy, direction, created_at DESC
                ), latest_backtests AS (
                    SELECT DISTINCT ON (symbol, interval, strategy)
                           symbol, interval, strategy, total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count, created_at
                    FROM backtest_runs
                    WHERE category=%s AND interval = ANY(%s::text[])
                    ORDER BY symbol, interval, strategy, created_at DESC
                ), latest_models AS (
                    SELECT DISTINCT ON (symbol, interval)
                           symbol, interval, roc_auc, precision_score, recall_score, created_at
                    FROM model_runs
                    WHERE category=%s AND interval = ANY(%s::text[])
                      AND created_at >= NOW() - (%s::text || ' hours')::interval
                    ORDER BY symbol, interval, created_at DESC
                ), latest_liq_raw AS (
                    SELECT DISTINCT ON (l.symbol) l.symbol, l.liquidity_score, l.spread_pct, l.turnover_24h,
                           l.open_interest_value, l.is_eligible, l.captured_at AS liquidity_captured_at,
                           (l.captured_at >= NOW() - (%s::text || ' minutes')::interval) AS liquidity_is_fresh
                    FROM liquidity_snapshots l
                    WHERE l.category=%s
                    ORDER BY l.symbol, l.captured_at DESC
                ), latest_liq AS (
                    SELECT symbol,
                           CASE WHEN liquidity_is_fresh THEN liquidity_score ELSE NULL END AS liquidity_score,
                           CASE WHEN liquidity_is_fresh THEN spread_pct ELSE NULL END AS spread_pct,
                           CASE WHEN liquidity_is_fresh THEN turnover_24h ELSE NULL END AS turnover_24h,
                           CASE WHEN liquidity_is_fresh THEN open_interest_value ELSE NULL END AS open_interest_value,
                           CASE WHEN liquidity_is_fresh THEN is_eligible ELSE NULL END AS is_eligible,
                           liquidity_captured_at,
                           CASE WHEN liquidity_captured_at IS NULL THEN 'missing'
                                WHEN liquidity_is_fresh THEN 'fresh' ELSE 'stale' END AS liquidity_status
                    FROM latest_liq_raw
                ), latest_quality AS (
                    SELECT category, symbol, interval, strategy, quality_status, quality_score, evidence_grade,
                           quality_reason, diagnostics AS quality_diagnostics, updated_at AS quality_updated_at,
                           backtest_run_id, last_backtest_at, expectancy, avg_trade_pnl, median_trade_pnl,
                           last_30d_return, last_90d_return, walk_forward_pass_rate, walk_forward_windows, walk_forward_summary
                    FROM strategy_quality
                    WHERE category=%s AND interval = ANY(%s::text[])
                ), latest_llm AS (
                    SELECT DISTINCT ON (signal_id)
                           signal_id, status AS llm_status, brief AS llm_brief, error AS llm_error,
                           model AS llm_model, updated_at AS llm_updated_at, duration_ms AS llm_duration_ms,
                           payload_hash AS llm_payload_hash
                    FROM llm_evaluations
                    ORDER BY signal_id, updated_at DESC
                )
                SELECT s.id, s.created_at, s.bar_time, s.category, s.symbol, s.interval, s.strategy, s.direction, s.confidence,
                       s.entry, s.stop_loss, s.take_profit, s.atr, s.ml_probability, s.sentiment_score, s.rationale,
                       b.total_return, b.max_drawdown, b.sharpe, b.win_rate, b.profit_factor, b.trades_count,
                       q.quality_status, q.quality_score, q.evidence_grade, q.quality_reason, q.quality_diagnostics, q.quality_updated_at, q.backtest_run_id, q.last_backtest_at,
                       q.expectancy, q.avg_trade_pnl, q.median_trade_pnl, q.last_30d_return, q.last_90d_return, q.walk_forward_pass_rate, q.walk_forward_windows, q.walk_forward_summary,
                       m.roc_auc, m.precision_score, m.recall_score,
                       l.liquidity_score, l.spread_pct, l.turnover_24h, l.open_interest_value, l.is_eligible,
                       l.liquidity_captured_at, l.liquidity_status,
                       e.llm_status, e.llm_brief, e.llm_error, e.llm_model, e.llm_updated_at, e.llm_duration_ms, e.llm_payload_hash,
                       (
                           COALESCE(s.confidence::float, 0) * 0.30
                         + LEAST(GREATEST(COALESCE(q.quality_score::float, 0) / 100.0, 0), 1) * 0.18
                         + CASE WHEN q.quality_status = 'APPROVED' THEN 0.08 WHEN q.quality_status = 'WATCHLIST' THEN 0.03 WHEN q.quality_status = 'REJECTED' THEN -0.18 ELSE -0.04 END
                         + CASE WHEN q.walk_forward_pass_rate IS NULL THEN 0 ELSE LEAST(GREATEST(q.walk_forward_pass_rate::float, 0), 1) * 0.05 END
                         + LEAST(GREATEST(COALESCE(b.profit_factor::float, 1) / 2.0, 0), 1) * 0.08 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
                         + LEAST(GREATEST(COALESCE(b.sharpe::float, 0) / 3.0, 0), 1) * 0.06 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
                         + LEAST(GREATEST(COALESCE(b.win_rate::float, 0), 0), 1) * 0.08 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
                         + LEAST(GREATEST((COALESCE(m.roc_auc::float, 0.5) - 0.5) / 0.25, 0), 1) * 0.15
                         + LEAST(GREATEST(COALESCE(l.liquidity_score::float, 0) / 8.0, 0), 1) * 0.10
                         + CASE WHEN COALESCE(l.is_eligible, FALSE) THEN 0.05 ELSE -0.10 END
                         + CASE WHEN COALESCE(l.spread_pct::float, 999) <= %s THEN 0.05 ELSE -0.05 END
                         - LEAST(GREATEST(COALESCE(b.max_drawdown::float, 0.2), 0), 1) * 0.10
                       ) AS research_score
                FROM latest_signals s
                LEFT JOIN latest_backtests b ON b.symbol=s.symbol AND b.interval=s.interval AND b.strategy=s.strategy
                LEFT JOIN latest_quality q ON q.symbol=s.symbol AND q.interval=s.interval AND q.strategy=s.strategy
                LEFT JOIN latest_models m ON m.symbol=s.symbol AND m.interval=s.interval
                LEFT JOIN latest_liq l ON l.symbol=s.symbol
                LEFT JOIN latest_llm e ON e.signal_id=s.id
                ORDER BY research_score DESC NULLS LAST, s.created_at DESC
                LIMIT %s
                """,
                (
                    category, context_intervals, settings.max_signal_age_hours,
                    category, context_intervals,
                    category, context_intervals, settings.ml_auto_train_ttl_hours,
                    settings.liquidity_snapshot_max_age_minutes, category,
                    category, context_intervals,
                    settings.max_spread_pct, query_limit,
                ),
            )
            rows = annotate_and_filter_fresh_signals(rows)
            rows = _apply_mtf_consensus(
                rows,
                entry_interval=settings.mtf_entry_interval,
                bias_interval=settings.mtf_bias_interval,
                regime_interval=settings.mtf_regime_interval,
            )
            if entry_only:
                rows = [row for row in rows if str(row.get("interval") or "").strip().upper() == entry_interval]
            rows = consolidate_operator_queue(annotate_recommendations(rows), limit=limit)
            return {"ok": True, "category": category, "entry_only": entry_only, "entry_interval": settings.mtf_entry_interval, "signals": rows}
    
        try:
            ensure_strategy_quality_storage()
        except Exception:
            pass
        rows = fetch_all(
            """
            WITH latest_signals AS (
                SELECT DISTINCT ON (category, symbol, interval, strategy, direction)
                       id, created_at, bar_time, category, symbol, interval, strategy, direction, confidence,
                       entry, stop_loss, take_profit, atr, ml_probability, sentiment_score, rationale
                FROM signals
                WHERE category=%s AND created_at >= NOW() - (%s::text || ' hours')::interval
                  AND bar_time IS NOT NULL
                ORDER BY category, symbol, interval, strategy, direction, created_at DESC
            ), latest_backtests AS (
                SELECT DISTINCT ON (symbol, interval, strategy)
                       symbol, interval, strategy, total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count, created_at
                FROM backtest_runs
                WHERE category=%s
                ORDER BY symbol, interval, strategy, created_at DESC
            ), latest_models AS (
                SELECT DISTINCT ON (symbol, interval)
                       symbol, interval, roc_auc, precision_score, recall_score, created_at
                FROM model_runs
                WHERE category=%s
                  AND created_at >= NOW() - (%s::text || ' hours')::interval
                ORDER BY symbol, interval, created_at DESC
            ), latest_liq_raw AS (
                SELECT DISTINCT ON (l.symbol) l.symbol, l.liquidity_score, l.spread_pct, l.turnover_24h,
                       l.open_interest_value, l.is_eligible, l.captured_at AS liquidity_captured_at,
                       (l.captured_at >= NOW() - (%s::text || ' minutes')::interval) AS liquidity_is_fresh
                FROM liquidity_snapshots l
                WHERE l.category=%s
                ORDER BY l.symbol, l.captured_at DESC
            ), latest_liq AS (
                SELECT symbol,
                       CASE WHEN liquidity_is_fresh THEN liquidity_score ELSE NULL END AS liquidity_score,
                       CASE WHEN liquidity_is_fresh THEN spread_pct ELSE NULL END AS spread_pct,
                       CASE WHEN liquidity_is_fresh THEN turnover_24h ELSE NULL END AS turnover_24h,
                       CASE WHEN liquidity_is_fresh THEN open_interest_value ELSE NULL END AS open_interest_value,
                       CASE WHEN liquidity_is_fresh THEN is_eligible ELSE NULL END AS is_eligible,
                       liquidity_captured_at,
                       CASE WHEN liquidity_captured_at IS NULL THEN 'missing'
                            WHEN liquidity_is_fresh THEN 'fresh' ELSE 'stale' END AS liquidity_status
                FROM latest_liq_raw
            ), latest_quality AS (
                SELECT category, symbol, interval, strategy, quality_status, quality_score, evidence_grade,
                       quality_reason, diagnostics AS quality_diagnostics, updated_at AS quality_updated_at,
                       backtest_run_id, last_backtest_at, expectancy, avg_trade_pnl, median_trade_pnl,
                       last_30d_return, last_90d_return, walk_forward_pass_rate, walk_forward_windows, walk_forward_summary
                FROM strategy_quality
                WHERE category=%s
            ), latest_llm AS (
                SELECT DISTINCT ON (signal_id)
                       signal_id, status AS llm_status, brief AS llm_brief, error AS llm_error,
                       model AS llm_model, updated_at AS llm_updated_at, duration_ms AS llm_duration_ms,
                       payload_hash AS llm_payload_hash
                FROM llm_evaluations
                ORDER BY signal_id, updated_at DESC
            )
            SELECT s.id, s.created_at, s.bar_time, s.category, s.symbol, s.interval, s.strategy, s.direction, s.confidence, s.entry, s.stop_loss, s.take_profit,
                   s.atr, s.ml_probability, s.sentiment_score, s.rationale,
                   b.total_return, b.max_drawdown, b.sharpe, b.win_rate, b.profit_factor, b.trades_count,
                   q.quality_status, q.quality_score, q.evidence_grade, q.quality_reason, q.quality_diagnostics, q.quality_updated_at, q.backtest_run_id, q.last_backtest_at,
                   q.expectancy, q.avg_trade_pnl, q.median_trade_pnl, q.last_30d_return, q.last_90d_return, q.walk_forward_pass_rate, q.walk_forward_windows, q.walk_forward_summary,
                   m.roc_auc, m.precision_score, m.recall_score,
                   l.liquidity_score, l.spread_pct, l.turnover_24h, l.open_interest_value, l.is_eligible,
                   l.liquidity_captured_at, l.liquidity_status,
                   e.llm_status, e.llm_brief, e.llm_error, e.llm_model, e.llm_updated_at, e.llm_duration_ms, e.llm_payload_hash,
                   (
                       COALESCE(s.confidence::float, 0) * 0.30
                     + LEAST(GREATEST(COALESCE(q.quality_score::float, 0) / 100.0, 0), 1) * 0.18
                     + CASE WHEN q.quality_status = 'APPROVED' THEN 0.08 WHEN q.quality_status = 'WATCHLIST' THEN 0.03 WHEN q.quality_status = 'REJECTED' THEN -0.18 ELSE -0.04 END
                     + CASE WHEN q.walk_forward_pass_rate IS NULL THEN 0 ELSE LEAST(GREATEST(q.walk_forward_pass_rate::float, 0), 1) * 0.05 END
                     + LEAST(GREATEST(COALESCE(b.profit_factor::float, 1) / 2.0, 0), 1) * 0.08 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
                     + LEAST(GREATEST(COALESCE(b.sharpe::float, 0) / 3.0, 0), 1) * 0.06 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
                     + LEAST(GREATEST(COALESCE(b.win_rate::float, 0), 0), 1) * 0.08 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
                     + LEAST(GREATEST((COALESCE(m.roc_auc::float, 0.5) - 0.5) / 0.25, 0), 1) * 0.15
                     + LEAST(GREATEST(COALESCE(l.liquidity_score::float, 0) / 8.0, 0), 1) * 0.10
                     + CASE WHEN COALESCE(l.is_eligible, FALSE) THEN 0.05 ELSE -0.10 END
                     + CASE WHEN COALESCE(l.spread_pct::float, 999) <= %s THEN 0.05 ELSE -0.05 END
                     - LEAST(GREATEST(COALESCE(b.max_drawdown::float, 0.2), 0), 1) * 0.10
                   ) AS research_score
            FROM latest_signals s
            LEFT JOIN latest_backtests b ON b.symbol=s.symbol AND b.interval=s.interval AND b.strategy=s.strategy
            LEFT JOIN latest_quality q ON q.symbol=s.symbol AND q.interval=s.interval AND q.strategy=s.strategy
            LEFT JOIN latest_models m ON m.symbol=s.symbol AND m.interval=s.interval
            LEFT JOIN latest_liq l ON l.symbol=s.symbol
            LEFT JOIN latest_llm e ON e.signal_id=s.id
            ORDER BY research_score DESC NULLS LAST, s.created_at DESC
            LIMIT %s
            """,
            (
                category, settings.max_signal_age_hours,
                category,
                category, settings.ml_auto_train_ttl_hours,
                settings.liquidity_snapshot_max_age_minutes, category,
                category,
                settings.max_spread_pct, limit,
            ),
        )
        rows = consolidate_operator_queue(annotate_recommendations(annotate_and_filter_fresh_signals(rows)), limit=limit)
        return {"ok": True, "category": category, "entry_only": False, "entry_interval": settings.mtf_entry_interval, "signals": rows}
    except Exception as exc:
        return {
            "ok": False,
            "category": category,
            "entry_only": entry_only,
            "entry_interval": settings.mtf_entry_interval,
            "signals": [],
            "error": _read_error(exc),
        }

@router.get("/research/rank")
def api_rank_candidates(category: str = settings.default_category, interval: str | None = None, limit: int = 30) -> dict[str, Any]:
    intervals: list[str] = []
    try:
        category = normalize_category(category)
        interval_value = interval or (settings.mtf_entry_interval if settings.mtf_consensus_enabled else settings.default_interval)
        if interval_value.strip().lower() in {"all", "multi", "mtf", "*"}:
            intervals = list(settings.signal_auto_intervals)
        else:
            intervals = normalize_intervals(interval_value)
        items = rank_candidates_multi(category, intervals, bounded_int(limit, "limit", 1, 200))
        return {
            "ok": True,
            "intervals": intervals,
            "entry_interval": settings.mtf_entry_interval,
            "recommendation_intervals": [settings.mtf_entry_interval] if settings.mtf_consensus_enabled else intervals,
            "context_intervals": [settings.mtf_bias_interval, settings.mtf_regime_interval] if settings.mtf_consensus_enabled else [],
            "items": items,
        }
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {
            "ok": False,
            "intervals": intervals,
            "entry_interval": settings.mtf_entry_interval,
            "recommendation_intervals": [settings.mtf_entry_interval] if settings.mtf_consensus_enabled else intervals,
            "context_intervals": [settings.mtf_bias_interval, settings.mtf_regime_interval] if settings.mtf_consensus_enabled else [],
            "items": [],
            "error": _read_error(exc),
        }


@router.get("/strategies/quality")
def api_strategy_quality(category: str = settings.default_category, interval: str | None = None, limit: int = 100) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        interval_value = normalize_interval(interval) if interval else None
        bounded_limit = bounded_int(limit, "limit", 1, 500)
        return {
            "ok": True,
            "summary": quality_summary(category),
            "items": latest_strategy_quality(category, interval_value, bounded_limit),
        }
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "summary": _empty_quality_summary(), "items": [], "error": _read_error(exc)}


@router.get("/strategies/lab")
def api_strategy_lab(category: str = settings.default_category, interval: str | None = None, limit: int = 200) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        interval_value = normalize_interval(interval) if interval else None
        bounded_limit = bounded_int(limit, "limit", 1, 500)
        return {"ok": True, **strategy_lab_snapshot(category, interval_value, bounded_limit)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        error = _read_error(exc)
        return {"ok": False, **_empty_strategy_lab_payload(error), "error": error}


@router.get("/trading-desk/diagnostics")
def api_trading_desk_diagnostics(category: str = settings.default_category, interval: str | None = None, limit: int = 200) -> dict[str, Any]:
    intervals: list[str] = []
    try:
        category = normalize_category(category)
        interval_value = interval or (settings.mtf_entry_interval if settings.mtf_consensus_enabled else settings.default_interval)
        if interval_value.strip().lower() in {"all", "multi", "mtf", "*"}:
            intervals = list(settings.signal_auto_intervals)
        else:
            intervals = normalize_intervals(interval_value)
        items = rank_candidates_multi(category, intervals, bounded_int(limit, "limit", 1, 500))
        return {"ok": True, "intervals": intervals, **trading_desk_diagnostics(items), "items": items}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        error = _read_error(exc)
        return {"ok": False, **_empty_trading_desk_payload(error, intervals), "error": error}


@router.get("/strategies/quality/refresh/status")
def api_strategy_quality_refresh_status() -> dict[str, Any]:
    return {"ok": True, "status": strategy_quality_refresher.status()}


@router.post("/strategies/quality/refresh")
def api_strategy_quality_refresh(limit: int = settings.strategy_quality_refresh_limit, wait: bool = False) -> dict[str, Any]:
    try:
        bounded_limit = bounded_int(limit, "limit", 1, 5000)
        if wait:
            # Синхронный режим оставлен для CLI/тестов и малых пачек. UI по умолчанию
            # использует фоновый запуск, чтобы оператор не получал timeout вместо статуса.
            return {
                "ok": True,
                "mode": "sync",
                "result": refresh_strategy_quality(
                    bounded_limit,
                    time_budget_sec=settings.strategy_quality_refresh_time_budget_sec,
                ),
                "status": strategy_quality_refresher.status(),
            }
        return {
            "ok": True,
            "mode": "background",
            "accepted": True,
            "status": strategy_quality_refresher.request_run(bounded_limit),
        }
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/backtest/run")
def api_backtest(req: BacktestRequest) -> dict[str, Any]:
    try:
        category = normalize_category(req.category)
        symbol = normalize_symbol(req.symbol)
        interval = normalize_interval(req.interval)
        if req.strategy not in _strategy_map():
            raise ValueError(f"Unknown strategy: {req.strategy}")
        return {"ok": True, "result": _run_backtest(category, symbol, interval, req.strategy, req.limit)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/backtest/background/status")
def api_backtest_background_status() -> dict[str, Any]:
    try:
        return {"ok": True, "status": background_backtester.status(), "summary": backtest_background_summary()}
    except Exception as exc:
        # Деградация backtest-статуса не должна ломать основной экран рекомендаций.
        return {"ok": False, "status": background_backtester.status(), "summary": {}, "error": str(exc)}


@router.post("/backtest/background/run-now")
def api_backtest_background_run_now() -> dict[str, Any]:
    background_backtester.start(force=True)
    background_backtester.request_run()
    return {"ok": True, "accepted": True, "status": background_backtester.status()}


@router.post("/ml/train")
def api_train(req: TrainRequest) -> dict[str, Any]:
    try:
        # sklearn/joblib тяжелые и нужны только для ML endpoints. Ленивый импорт не дает
        # ML-зависимостям замедлять или ломать запуск основного research/API контура.
        from .ml import train_model

        return {"ok": True, "result": train_model(normalize_category(req.category), normalize_symbol(req.symbol), normalize_interval(req.interval), req.horizon_bars)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ml/predict/latest")
def api_predict(symbol: str = "BTCUSDT", category: str = settings.default_category, interval: str = settings.default_interval, horizon_bars: int = 12) -> dict[str, Any]:
    try:
        # Ленивый импорт по той же причине, что и в /ml/train: торговая витрина и
        # фоновые сигналы должны стартовать даже если локальный sklearn проблемный.
        from .ml import predict_latest

        return {"ok": True, "result": predict_latest(normalize_category(category), normalize_symbol(symbol), normalize_interval(interval), bounded_int(horizon_bars, "horizon_bars", 1, 240))}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/llm/brief")
def api_llm_brief(req: BriefRequest) -> dict[str, Any]:
    payload = req.payload or {}
    if req.signal_id is not None:
        row = fetch_one("SELECT * FROM signals WHERE id=%s", (req.signal_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Signal not found")
        payload = row
    try:
        return {"ok": True, "brief": market_brief(payload)}
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/llm/background/status")
def api_llm_background_status() -> dict[str, Any]:
    try:
        return {"ok": True, "status": background_evaluator.status(), "summary": evaluation_summary()}
    except Exception as exc:
        # Статус LLM не должен ломать основной торговый экран: отдаем деградированную
        # диагностику, чтобы UI явно показал проблему фонового анализа.
        return {"ok": False, "status": background_evaluator.status(), "summary": {}, "error": str(exc)}


@router.post("/llm/background/run-now")
def api_llm_background_run_now() -> dict[str, Any]:
    background_evaluator.start(force=True)
    background_evaluator.request_run()
    return {"ok": True, "accepted": True, "status": background_evaluator.status()}


@router.get("/llm/evaluations/latest")
def api_llm_evaluations_latest(limit: int = 100) -> dict[str, Any]:
    try:
        return {"ok": True, "items": latest_evaluations(bounded_int(limit, "limit", 1, 500))}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "items": [], "error": _read_error(exc)}


@router.get("/equity/latest")
def latest_equity(limit: int = 10) -> dict[str, Any]:
    try:
        limit = bounded_int(limit, "limit", 1, 100)
        runs = fetch_all(
            """
            SELECT id, created_at, symbol, interval, strategy, initial_equity, final_equity, total_return,
                   max_drawdown, sharpe, win_rate, profit_factor, trades_count, equity_curve
            FROM backtest_runs
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return {"ok": True, "runs": runs}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "runs": [], "error": _read_error(exc)}


@router.get("/news/latest")
def latest_news(symbol: str = "BTCUSDT", limit: int = 30) -> dict[str, Any]:
    try:
        symbol = normalize_symbol(symbol)
        limit = bounded_int(limit, "limit", 1, 200)
        rows = fetch_all(
            """
            SELECT source, symbol, published_at, title, url, source_domain, sentiment_score, llm_score, llm_label
            FROM news_items
            WHERE symbol=%s OR symbol='MARKET'
            ORDER BY published_at DESC NULLS LAST, created_at DESC
            LIMIT %s
            """,
            (symbol, limit),
        )
        return {"ok": True, "news": rows}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "news": [], "error": _read_error(exc)}
