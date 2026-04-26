from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .backtest import STRATEGY_MAP, run_backtest
from .backtest_background import background_backtester, backtest_background_summary
from .bybit_client import sync_market_bundle
from .config import settings
from .db import fetch_all, fetch_one
from .llm import LLMUnavailable, market_brief
from .llm_background import background_evaluator, evaluation_summary, latest_evaluations
from .research import rank_candidates
from .sentiment import sentiment_summary, sync_sentiment_bundle
from .signal_background import signal_refresher
from .strategies import build_latest_signals, persist_signals
from .symbols import build_universe, latest_liquidity, latest_universe, refresh_liquidity
from .validation import bounded_int, normalize_category, normalize_interval, normalize_symbol, normalize_symbols

router = APIRouter(prefix="/api")


class MarketSyncRequest(BaseModel):
    category: str = settings.default_category
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols), min_length=1)
    interval: str = settings.default_interval
    days: int = Field(default=90, ge=1, le=settings.max_sync_days)


class SentimentSyncRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols), min_length=1)
    days: int = Field(default=settings.sentiment_lookback_days, ge=1, le=60)
    use_llm: bool = False
    category: str = settings.default_category
    interval: str = settings.default_interval


class SignalBuildRequest(BaseModel):
    category: str = settings.default_category
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols), min_length=1)
    interval: str = settings.default_interval


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


@router.get("/status")
def status() -> dict[str, Any]:
    db = fetch_one("SELECT NOW() AS now")
    latest = fetch_one("SELECT COUNT(*) AS candles FROM candles")
    return {
        "ok": True,
        "db_time": str(db["now"]) if db else None,
        "candles": int(latest["candles"]) if latest else 0,
        "default_symbols": settings.default_symbols,
        "core_symbols": settings.core_symbols,
        "symbol_mode": settings.symbol_mode,
        "strategies": sorted(set(STRATEGY_MAP.keys())),
        "risk_controls": {
            "risk_per_trade": settings.risk_per_trade,
            "max_position_notional_usdt": settings.max_position_notional_usdt,
            "max_leverage": settings.max_leverage,
            "require_liquidity_for_signals": settings.require_liquidity_for_signals,
        },
        "max_signal_age_hours": settings.max_signal_age_hours,
        "backtest_auto": {
            "enabled": settings.backtest_auto_enabled,
            "interval_sec": settings.backtest_auto_interval_sec,
            "max_candidates": settings.backtest_auto_max_candidates,
            "ttl_hours": settings.backtest_auto_ttl_hours,
        },
        "signal_auto_refresh": {
            "enabled": settings.signal_auto_refresh_enabled,
            "interval_sec": settings.signal_auto_refresh_interval_sec,
            "max_symbols": settings.signal_auto_max_symbols,
            "sync_days": settings.signal_auto_sync_days,
            "sync_sentiment": settings.signal_auto_sync_sentiment,
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


@router.post("/sync/market")
def sync_market(req: MarketSyncRequest) -> dict[str, Any]:
    result = {}
    try:
        category = normalize_category(req.category)
        interval = normalize_interval(req.interval)
        symbols = normalize_symbols(req.symbols)
        days = bounded_int(req.days, "days", 1, settings.max_sync_days)
        for symbol in symbols:
            result[symbol] = sync_market_bundle(category, symbol, interval, days)
        return {"ok": True, "result": result}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sync/sentiment")
def sync_sentiment(req: SentimentSyncRequest) -> dict[str, Any]:
    try:
        category = normalize_category(req.category)
        interval = normalize_interval(req.interval)
        symbols = normalize_symbols(req.symbols)
        days = bounded_int(req.days, "days", 1, 60)
        return {"ok": True, "result": sync_sentiment_bundle(symbols, days, req.use_llm, category, interval)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/sentiment/summary")
def api_sentiment_summary(symbol: str = "BTCUSDT", limit: int = 20) -> dict[str, Any]:
    try:
        return {"ok": True, "result": sentiment_summary(normalize_symbol(symbol), bounded_int(limit, "limit", 1, 200))}
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/signals/build")
def build_signals(req: SignalBuildRequest) -> dict[str, Any]:
    output = {}
    try:
        category = normalize_category(req.category)
        interval = normalize_interval(req.interval)
        symbols = normalize_symbols(req.symbols)
        total_inserted = 0
        for symbol in symbols:
            signals = build_latest_signals(category, symbol, interval)
            inserted = persist_signals(category, symbol, interval, signals)
            total_inserted += int(inserted or 0)
            output[symbol] = {"built": len(signals), "upserted": inserted, "signals": [s.__dict__ for s in signals]}
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
    signal_refresher.request_run()
    return {"ok": True, "status": signal_refresher.status()}


@router.get("/signals/latest")
def latest_signals(limit: int = 50) -> dict[str, Any]:
    try:
        limit = bounded_int(limit, "limit", 1, 500)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    rows = fetch_all(
        """
        SELECT id, created_at, bar_time, symbol, interval, strategy, direction, confidence, entry, stop_loss, take_profit,
               atr, ml_probability, sentiment_score, rationale
        FROM signals
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return {"ok": True, "signals": rows}


@router.get("/research/rank")
def api_rank_candidates(category: str = settings.default_category, interval: str = settings.default_interval, limit: int = 30) -> dict[str, Any]:
    try:
        return {"ok": True, "items": rank_candidates(normalize_category(category), normalize_interval(interval), bounded_int(limit, "limit", 1, 200))}
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/backtest/run")
def api_backtest(req: BacktestRequest) -> dict[str, Any]:
    try:
        category = normalize_category(req.category)
        symbol = normalize_symbol(req.symbol)
        interval = normalize_interval(req.interval)
        if req.strategy not in STRATEGY_MAP:
            raise ValueError(f"Unknown strategy: {req.strategy}")
        return {"ok": True, "result": run_backtest(category, symbol, interval, req.strategy, req.limit)}
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
    background_backtester.request_run()
    return {"ok": True, "status": background_backtester.status()}


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
    background_evaluator.request_run()
    return {"ok": True, "status": background_evaluator.status()}


@router.get("/llm/evaluations/latest")
def api_llm_evaluations_latest(limit: int = 100) -> dict[str, Any]:
    try:
        return {"ok": True, "items": latest_evaluations(bounded_int(limit, "limit", 1, 500))}
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/equity/latest")
def latest_equity(limit: int = 10) -> dict[str, Any]:
    try:
        limit = bounded_int(limit, "limit", 1, 100)
    except ValueError as exc:
        raise _bad_request(exc) from exc
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


@router.get("/news/latest")
def latest_news(symbol: str = "BTCUSDT", limit: int = 30) -> dict[str, Any]:
    try:
        symbol = normalize_symbol(symbol)
        limit = bounded_int(limit, "limit", 1, 200)
    except ValueError as exc:
        raise _bad_request(exc) from exc
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
