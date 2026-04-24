from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .backtest import STRATEGY_MAP, run_backtest
from .bybit_client import sync_market_bundle
from .config import settings
from .db import fetch_all, fetch_one
from .llm import LLMUnavailable, market_brief
from .ml import predict_latest, train_model
from .research import rank_candidates
from .sentiment import sentiment_summary, sync_sentiment_bundle
from .strategies import build_latest_signals, persist_signals
from .symbols import build_universe, latest_liquidity, latest_universe, refresh_liquidity

router = APIRouter(prefix="/api")


class MarketSyncRequest(BaseModel):
    category: str = settings.default_category
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols))
    interval: str = settings.default_interval
    days: int = 90


class SentimentSyncRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols))
    days: int = settings.sentiment_lookback_days
    use_llm: bool = False
    category: str = settings.default_category
    interval: str = settings.default_interval


class SignalBuildRequest(BaseModel):
    category: str = settings.default_category
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols))
    interval: str = settings.default_interval


class BacktestRequest(BaseModel):
    category: str = settings.default_category
    symbol: str = "BTCUSDT"
    interval: str = settings.default_interval
    strategy: str = "donchian_atr_breakout"
    limit: int = 5000


class TrainRequest(BaseModel):
    category: str = settings.default_category
    symbol: str = "BTCUSDT"
    interval: str = settings.default_interval
    horizon_bars: int = 12


class BriefRequest(BaseModel):
    signal_id: int | None = None
    payload: dict[str, Any] | None = None


class UniverseRequest(BaseModel):
    category: str = settings.default_category
    mode: str = settings.symbol_mode
    limit: int = settings.universe_limit
    refresh: bool = True


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
        return {"ok": True, "result": refresh_liquidity(category)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/symbols/liquidity/latest")
def api_latest_liquidity(category: str = settings.default_category, limit: int = 50) -> dict[str, Any]:
    return {"ok": True, "items": latest_liquidity(category, limit)}


@router.post("/symbols/universe/build")
def api_build_universe(req: UniverseRequest) -> dict[str, Any]:
    try:
        return {"ok": True, "result": build_universe(req.category, req.mode, req.limit, req.refresh)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/symbols/universe/latest")
def api_latest_universe(category: str = settings.default_category, mode: str | None = None, limit: int = 50) -> dict[str, Any]:
    return {"ok": True, "items": latest_universe(category, mode, limit)}


@router.post("/sync/market")
def sync_market(req: MarketSyncRequest) -> dict[str, Any]:
    result = {}
    try:
        for symbol in req.symbols:
            result[symbol.upper()] = sync_market_bundle(req.category, symbol, req.interval, req.days)
        return {"ok": True, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sync/sentiment")
def sync_sentiment(req: SentimentSyncRequest) -> dict[str, Any]:
    try:
        return {"ok": True, "result": sync_sentiment_bundle(req.symbols, req.days, req.use_llm, req.category, req.interval)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/sentiment/summary")
def api_sentiment_summary(symbol: str = "BTCUSDT", limit: int = 20) -> dict[str, Any]:
    return {"ok": True, "result": sentiment_summary(symbol, limit)}


@router.post("/signals/build")
def build_signals(req: SignalBuildRequest) -> dict[str, Any]:
    output = {}
    try:
        for symbol in req.symbols:
            signals = build_latest_signals(req.category, symbol, req.interval)
            inserted = persist_signals(req.category, symbol, req.interval, signals)
            output[symbol.upper()] = {"built": len(signals), "inserted": inserted, "signals": [s.__dict__ for s in signals]}
        return {"ok": True, "result": output}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/signals/latest")
def latest_signals(limit: int = 50) -> dict[str, Any]:
    rows = fetch_all(
        """
        SELECT id, created_at, symbol, interval, strategy, direction, confidence, entry, stop_loss, take_profit,
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
    return {"ok": True, "items": rank_candidates(category, interval, limit)}


@router.post("/backtest/run")
def api_backtest(req: BacktestRequest) -> dict[str, Any]:
    try:
        return {"ok": True, "result": run_backtest(req.category, req.symbol, req.interval, req.strategy, req.limit)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ml/train")
def api_train(req: TrainRequest) -> dict[str, Any]:
    try:
        return {"ok": True, "result": train_model(req.category, req.symbol, req.interval, req.horizon_bars)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ml/predict/latest")
def api_predict(symbol: str = "BTCUSDT", category: str = settings.default_category, interval: str = settings.default_interval, horizon_bars: int = 12) -> dict[str, Any]:
    try:
        return {"ok": True, "result": predict_latest(category, symbol, interval, horizon_bars)}
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


@router.get("/equity/latest")
def latest_equity(limit: int = 10) -> dict[str, Any]:
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
    rows = fetch_all(
        """
        SELECT source, symbol, published_at, title, url, source_domain, sentiment_score, llm_score, llm_label
        FROM news_items
        WHERE symbol=%s OR symbol='MARKET'
        ORDER BY published_at DESC NULLS LAST, created_at DESC
        LIMIT %s
        """,
        (symbol.upper(), limit),
    )
    return {"ok": True, "news": rows}
