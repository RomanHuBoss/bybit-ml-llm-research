from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field


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
from .db import execute, fetch_all, fetch_one
from .llm import LLMUnavailable, market_brief
from .llm_background import background_evaluator, evaluation_summary, latest_evaluations
from .operator_queue import consolidate_operator_queue
from .recommendation import annotate_recommendations, ensure_operator_decisions
from .trade_contract import DECISION_SOURCE, RECOMMENDATION_CONTRACT_VERSION, no_trade_decision_snapshot
from .recommendation_outcomes import evaluate_due_recommendation_outcomes
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




class StrictAPIModel(BaseModel):
    """Base class for externally supplied API bodies.

    Unknown fields are rejected so frontend/backend drift is visible immediately
    instead of being silently ignored by Pydantic.
    """

    model_config = ConfigDict(extra="forbid")


class MarketSyncRequest(StrictAPIModel):
    category: str = settings.default_category
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols), min_length=1)
    interval: str = settings.default_interval
    intervals: list[str] | None = None
    days: int = Field(default=90, ge=1, le=settings.max_sync_days)


class SentimentSyncRequest(StrictAPIModel):
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols), min_length=1)
    days: int = Field(default=settings.sentiment_lookback_days, ge=1, le=60)
    use_llm: bool = False
    category: str = settings.default_category
    interval: str = settings.default_interval
    intervals: list[str] | None = None


class SignalBuildRequest(StrictAPIModel):
    category: str = settings.default_category
    symbols: list[str] = Field(default_factory=lambda: list(settings.default_symbols), min_length=1)
    interval: str = settings.default_interval
    intervals: list[str] | None = None


class BacktestRequest(StrictAPIModel):
    category: str = settings.default_category
    symbol: str = "BTCUSDT"
    interval: str = settings.default_interval
    strategy: str = "donchian_atr_breakout"
    limit: int = Field(default=5000, ge=300, le=100000)


class TrainRequest(StrictAPIModel):
    category: str = settings.default_category
    symbol: str = "BTCUSDT"
    interval: str = settings.default_interval
    horizon_bars: int = Field(default=12, ge=1, le=240)


class BriefRequest(StrictAPIModel):
    signal_id: int | None = None
    payload: dict[str, Any] | None = None


class UniverseRequest(StrictAPIModel):
    category: str = settings.default_category
    mode: str = settings.symbol_mode
    limit: int = Field(default=settings.universe_limit, ge=1, le=100)
    refresh: bool = True


class OperatorActionRequest(StrictAPIModel):
    action: Literal["skip", "wait_confirmation", "manual_review", "close_invalidated", "paper_opened"]
    notes: str | None = Field(default=None, max_length=2000)
    observed_price: float | None = Field(default=None, gt=0)




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




def _symbol_csv(symbols: str | None) -> list[str]:
    if not symbols:
        return list(settings.default_symbols)
    return normalize_symbols([part for part in str(symbols).split(",") if part.strip()])


def _latest_quote_rows(category: str, interval: str, symbols: list[str]) -> list[dict[str, Any]]:
    return fetch_all(
        """
        WITH latest AS (
            SELECT DISTINCT ON (symbol)
                   category, symbol, interval, start_time AS last_price_time, close AS last_price,
                   open, high, low, close, volume, turnover,
                   (start_time >= NOW() - (%s::text || ' hours')::interval) AS is_recent
            FROM candles
            WHERE category=%s AND interval=%s AND symbol = ANY(%s::text[])
            ORDER BY symbol, start_time DESC
        )
        SELECT *, CASE WHEN is_recent THEN 'fresh' ELSE 'stale' END AS data_status
        FROM latest
        ORDER BY symbol
        """,
        (settings.max_signal_age_hours, category, interval, symbols),
    )


def _recommendation_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"review_entry": 0, "research_candidate": 0, "wait": 0, "blocked": 0, "expired": 0, "invalid": 0, "missed_entry": 0}
    actionable = 0
    stale = 0
    moved_away = 0
    for item in items:
        status = str(item.get("recommendation_status") or (item.get("recommendation") or {}).get("recommendation_status") or "wait")
        counts[status] = counts.get(status, 0) + 1
        actionable += 1 if item.get("is_actionable") or (item.get("recommendation") or {}).get("is_actionable") else 0
        price_status = str(item.get("price_status") or (item.get("recommendation") or {}).get("price_status") or "")
        stale += 1 if price_status == "stale" else 0
        moved_away += 1 if price_status == "moved_away" else 0
    return {
        "total": len(items),
        "actionable": actionable,
        "by_status": counts,
        "stale": stale,
        "moved_away": moved_away,
        "contract": RECOMMENDATION_CONTRACT_VERSION,
        "previous_contract": "recommendation_v38",
    }




def _market_state_for_recommendations(*, payload_ok: bool, recommendations: list[dict[str, Any]], error: str | None = None) -> dict[str, Any]:
    """Explain active recommendation state without forcing UI to infer NO_TRADE from an empty list."""

    summary = _recommendation_summary(recommendations)
    if error:
        status = "api_error"
        explanation = f"Recommendation API degraded: {error}. Новые входы запрещены до восстановления backend/DB."
    elif not payload_ok:
        status = "unavailable"
        explanation = "Recommendation API недоступен. Вход по умолчанию запрещён; проверьте PostgreSQL, миграции и фоновые задачи."
    elif not recommendations:
        status = "no_trade"
        explanation = "Нет активных свежих рекомендаций. Это штатное NO_TRADE/WAIT-состояние: рынок может быть без валидного сетапа, данные могут ожидать синхронизацию или quality gate не дал REVIEW_ENTRY."
    elif summary.get("actionable", 0) <= 0:
        status = "no_actionable_trade"
        explanation = "Сетапы есть, но ни один не прошёл серверный contract до actionable REVIEW_ENTRY. Оператор должен смотреть причины блокировки, а не открывать сделку."
    elif summary.get("stale", 0) > 0:
        status = "partially_stale"
        explanation = "Часть рекомендаций построена на устаревшей цене. Перед входом требуется пересчёт или ручная проверка актуальности."
    else:
        status = "active"
        explanation = "Есть рекомендации, прошедшие серверный advisory contract. Это не приказ на сделку: требуется ручная проверка цены, стакана, риска и условий отмены."
    return {
        "status": status,
        "contract": RECOMMENDATION_CONTRACT_VERSION,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "explanation": explanation,
    }


def _recommendation_contract_metadata() -> dict[str, Any]:
    return {
        "version": RECOMMENDATION_CONTRACT_VERSION,
        "active_endpoint": "/api/recommendations/active",
        "detail_endpoint": "/api/recommendations/{signal_id}",
        "history_endpoint": "/api/recommendations/history",
        "quality_endpoint": "/api/recommendations/quality",
        "frontend_source_of_truth": "recommendations_active",
        "fallback_source": "rank_candidates_only_when_active_endpoint_empty_or_unavailable",
        "confidence_semantics": "confidence_score is an engineering setup score, not an exact win probability",
        "allowed_directions": ["long", "short", "no_trade"],
        "allowed_statuses": ["review_entry", "research_candidate", "wait", "blocked", "expired", "invalid", "missed_entry"],
        "allowed_price_statuses": ["entry_zone", "extended", "moved_away", "stale", "unknown", "no_setup"],
        "required_recommendation_fields": [
            "symbol", "trade_direction", "entry", "stop_loss", "take_profit",
            "risk_pct", "expected_reward_pct", "risk_reward", "net_risk_reward", "confidence_score",
            "expires_at", "checked_at", "ttl_status", "ttl_seconds_left",
            "recommendation_explanation", "signal_breakdown",
            "price_actionability", "contract_health", "decision_source", "frontend_may_recalculate",
            "intrabar_execution_model", "same_bar_stop_first_reason",
            "signal_breakdown.outcome_quality",
        ],
        "intrabar_execution_policy": "conservative_ohlc_stop_loss_first; same-bar SL/TP is marked as stop_loss_same_bar_ambiguous",
        "price_gate_policy": "entry_zone_only_for_actionable_review",
        "decision_source": DECISION_SOURCE,
        "decision_source_literal": "server_enriched_contract_v40",
        "operator_queue_policy": "operator_queue_consolidates_before_contract_enrichment",
        "frontend_may_recalculate": False,
        "frontend_rule": "render only server-enriched recommendation contract fields; do not recompute final trade direction or risk math on the client",
    }


def _quality_drawdown_payload(category: str, interval_filter: str | None = None) -> dict[str, Any]:
    """Compute recommendation-level drawdown from realized R sequence.

    This is intentionally based on completed recommendation outcomes rather than
    strategy backtest rows so the UI can separate live/paper recommendation
    quality from historical strategy evidence.
    """
    params: list[Any] = [category]
    interval_sql = ""
    if interval_filter:
        interval_sql = " AND s.interval=%s"
        params.append(interval_filter)
    row = fetch_one(
        f"""
        WITH ordered AS (
            SELECT o.evaluated_at, COALESCE(o.realized_r, 0)::float AS realized_r,
                   SUM(COALESCE(o.realized_r, 0)::float) OVER (ORDER BY o.evaluated_at, o.signal_id) AS equity_r
            FROM recommendation_outcomes o
            JOIN signals s ON s.id=o.signal_id
            WHERE s.category=%s {interval_sql}
              AND o.outcome_status <> 'open'
        ), curve AS (
            SELECT evaluated_at, realized_r, equity_r,
                   MAX(equity_r) OVER (ORDER BY evaluated_at) AS peak_r
            FROM ordered
        )
        SELECT COUNT(*)::int AS evaluated,
               COALESCE(MIN(equity_r - peak_r), 0)::float AS max_drawdown_r,
               COALESCE(SUM(realized_r), 0)::float AS cumulative_r,
               AVG(realized_r)::float AS expectancy_r
        FROM curve
        """,
        tuple(params),
    ) or {}
    evaluated = int(row.get("evaluated") or 0)
    return {
        "evaluated": evaluated,
        "max_drawdown_r": float(row.get("max_drawdown_r") or 0.0),
        "cumulative_r": float(row.get("cumulative_r") or 0.0),
        "expectancy_r": row.get("expectancy_r"),
        "explanation": (
            "Недостаточно завершённых рекомендаций для устойчивой оценки drawdown."
            if evaluated < 30 else
            "Drawdown рассчитан по последовательности завершённых рекомендаций в единицах R."
        ),
    }


def _quality_outcome_status_counts(category: str, interval_filter: str | None = None) -> list[dict[str, Any]]:
    params: list[Any] = [category]
    interval_sql = ""
    if interval_filter:
        interval_sql = " AND s.interval=%s"
        params.append(interval_filter)
    return fetch_all(
        f"""
        SELECT o.outcome_status, COUNT(*)::int AS count,
               COUNT(*) FILTER (WHERE COALESCE((o.notes->>'ambiguous_exit')::boolean, false)
                                OR COALESCE((o.notes->>'same_bar_stop_first')::boolean, false)
                                OR o.notes->>'exit_reason' = 'stop_loss_same_bar_ambiguous')::int AS ambiguous_stop_first_count
        FROM recommendation_outcomes o
        JOIN signals s ON s.id=o.signal_id
        WHERE s.category=%s {interval_sql}
        GROUP BY o.outcome_status
        ORDER BY count DESC, o.outcome_status
        """,
        tuple(params),
    )


def _quality_segment_rows(category: str, interval_filter: str | None = None) -> dict[str, Any]:
    params: list[Any] = [category]
    interval_sql = ""
    if interval_filter:
        interval_sql = " AND s.interval=%s"
        params.append(interval_filter)
    by_symbol = fetch_all(
        f"""
        SELECT s.symbol, COUNT(*)::int AS evaluated,
               AVG(o.realized_r)::float AS average_r,
               SUM(CASE WHEN o.realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) AS winrate,
               SUM(GREATEST(o.realized_r,0))::float / NULLIF(ABS(SUM(LEAST(o.realized_r,0)))::float,0) AS profit_factor,
               AVG(o.max_favorable_excursion_r)::float AS avg_mfe_r,
               AVG(o.max_adverse_excursion_r)::float AS avg_mae_r,
               COUNT(*) FILTER (WHERE COALESCE((o.notes->>'ambiguous_exit')::boolean, false)
                                OR COALESCE((o.notes->>'same_bar_stop_first')::boolean, false)
                                OR o.notes->>'exit_reason' = 'stop_loss_same_bar_ambiguous')::int AS ambiguous_stop_first_count
        FROM recommendation_outcomes o
        JOIN signals s ON s.id=o.signal_id
        WHERE s.category=%s {interval_sql}
          AND o.outcome_status <> 'open'
        GROUP BY s.symbol
        ORDER BY evaluated DESC, average_r DESC NULLS LAST
        LIMIT 50
        """,
        tuple(params),
    )
    by_strategy = fetch_all(
        f"""
        SELECT s.interval, s.strategy, COUNT(*)::int AS evaluated,
               AVG(o.realized_r)::float AS average_r,
               SUM(CASE WHEN o.realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) AS winrate,
               SUM(GREATEST(o.realized_r,0))::float / NULLIF(ABS(SUM(LEAST(o.realized_r,0)))::float,0) AS profit_factor,
               AVG(o.max_favorable_excursion_r)::float AS avg_mfe_r,
               AVG(o.max_adverse_excursion_r)::float AS avg_mae_r
        FROM recommendation_outcomes o
        JOIN signals s ON s.id=o.signal_id
        WHERE s.category=%s {interval_sql}
          AND o.outcome_status <> 'open'
        GROUP BY s.interval, s.strategy
        ORDER BY evaluated DESC, average_r DESC NULLS LAST
        LIMIT 80
        """,
        tuple(params),
    )
    by_confidence = fetch_all(
        f"""
        SELECT CASE
                 WHEN s.confidence < 0.55 THEN '<55%'
                 WHEN s.confidence < 0.65 THEN '55-65%'
                 WHEN s.confidence < 0.75 THEN '65-75%'
                 ELSE '>=75%'
               END AS confidence_bucket,
               COUNT(*)::int AS evaluated,
               AVG(o.realized_r)::float AS average_r,
               SUM(CASE WHEN o.realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) AS winrate,
               SUM(GREATEST(o.realized_r,0))::float / NULLIF(ABS(SUM(LEAST(o.realized_r,0)))::float,0) AS profit_factor
        FROM recommendation_outcomes o
        JOIN signals s ON s.id=o.signal_id
        WHERE s.category=%s {interval_sql}
          AND o.outcome_status <> 'open'
        GROUP BY confidence_bucket
        ORDER BY confidence_bucket
        """,
        tuple(params),
    )
    return {"by_symbol": by_symbol, "by_strategy": by_strategy, "by_confidence_bucket": by_confidence}


def _sample_confidence_label(sample_size: int) -> str:
    if sample_size >= 100:
        return "high"
    if sample_size >= 30:
        return "medium"
    if sample_size > 0:
        return "low"
    return "none"


def _similar_recommendation_history(signal_id: int, category: str, limit: int = 30) -> dict[str, Any]:
    """Return outcome history for the same symbol/TF/strategy/direction as a recommendation.

    This is deliberately separate from the final recommendation score: the UI must
    explain whether historical evidence is broad enough without treating it as the
    probability that the current signal will win.
    """
    bounded_limit = bounded_int(limit, "limit", 1, 200)
    base = fetch_one(
        """
        SELECT id, category, symbol, interval, strategy, direction, confidence, bar_time
        FROM signals
        WHERE id=%s AND category=%s
        """,
        (int(signal_id), category),
    )
    if not base:
        return {
            "ok": False,
            "recommendation_id": int(signal_id),
            "summary": {},
            "items": [],
            "error": "Recommendation not found",
        }
    params = (category, base.get("symbol"), base.get("interval"), base.get("strategy"), base.get("direction"))
    summary = fetch_one(
        """
        SELECT COUNT(*)::int AS evaluated,
               AVG(o.realized_r)::float AS average_r,
               SUM(CASE WHEN o.realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) AS winrate,
               SUM(GREATEST(o.realized_r,0))::float / NULLIF(ABS(SUM(LEAST(o.realized_r,0)))::float,0) AS profit_factor,
               AVG(o.max_favorable_excursion_r)::float AS avg_mfe_r,
               AVG(o.max_adverse_excursion_r)::float AS avg_mae_r,
               COUNT(*) FILTER (WHERE COALESCE((o.notes->>'ambiguous_exit')::boolean, false)
                                OR COALESCE((o.notes->>'same_bar_stop_first')::boolean, false)
                                OR o.notes->>'exit_reason' = 'stop_loss_same_bar_ambiguous')::int AS ambiguous_stop_first_count,
               MAX(o.evaluated_at) AS last_evaluated_at
        FROM recommendation_outcomes o
        JOIN signals s ON s.id=o.signal_id
        WHERE s.category=%s
          AND s.symbol=%s
          AND s.interval=%s
          AND s.strategy=%s
          AND s.direction=%s
          AND o.outcome_status <> 'open'
        """,
        params,
    ) or {}
    items = fetch_all(
        """
        SELECT s.id AS signal_id, s.bar_time, s.created_at, s.confidence,
               s.entry, s.stop_loss, s.take_profit, s.risk_reward,
               o.outcome_status, o.exit_time, o.exit_price, o.realized_r,
               o.max_favorable_excursion_r, o.max_adverse_excursion_r,
               o.bars_observed, o.evaluated_at, o.notes
        FROM recommendation_outcomes o
        JOIN signals s ON s.id=o.signal_id
        WHERE s.category=%s
          AND s.symbol=%s
          AND s.interval=%s
          AND s.strategy=%s
          AND s.direction=%s
          AND o.outcome_status <> 'open'
        ORDER BY COALESCE(o.exit_time, o.evaluated_at, s.bar_time) DESC NULLS LAST
        LIMIT %s
        """,
        (*params, bounded_limit),
    )
    evaluated = int((summary or {}).get("evaluated") or 0)
    confidence_level = _sample_confidence_label(evaluated)
    if evaluated < 30:
        explanation = (
            f"Похожих завершённых рекомендаций: {evaluated}. Этого мало для высокой статистической уверенности; "
            "используйте историю только как контекст и снижайте риск."
        )
    elif evaluated < 100:
        explanation = (
            f"Похожих завершённых рекомендаций: {evaluated}. Выборка умеренная: можно учитывать PF/average R, "
            "но текущий сигнал всё равно проверяется отдельно."
        )
    else:
        explanation = (
            f"Похожих завершённых рекомендаций: {evaluated}. Выборка достаточная для рабочего контроля качества, "
            "но не является гарантией результата текущей сделки."
        )
    return {
        "ok": True,
        "recommendation_id": int(signal_id),
        "match": {
            "symbol": base.get("symbol"),
            "interval": base.get("interval"),
            "strategy": base.get("strategy"),
            "direction": base.get("direction"),
        },
        "summary": {
            **dict(summary or {}),
            "statistical_confidence": confidence_level,
            "explanation": explanation,
            "metric_semantics": "История похожих сигналов описывает прошлые завершённые рекомендации и не является вероятностью прибыли текущего сигнала.",
        },
        "items": items,
    }


def _operator_action_status(action: str) -> str:
    return {
        "skip": "skipped_by_operator",
        "wait_confirmation": "waiting_confirmation",
        "manual_review": "manual_review_started",
        "close_invalidated": "invalidated_by_operator",
        "paper_opened": "paper_opened",
    }.get(action, "operator_action_logged")


def _recommendation_base_sql(where_sql: str) -> str:
    return f"""
    WITH latest_backtests AS (
        SELECT DISTINCT ON (symbol, interval, strategy)
               symbol, interval, strategy, total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count, created_at
        FROM backtest_runs
        WHERE category=%s
        ORDER BY symbol, interval, strategy, created_at DESC
    ), latest_quality AS (
        SELECT category, symbol, interval, strategy, quality_status, quality_score, evidence_grade,
               quality_reason, diagnostics AS quality_diagnostics, updated_at AS quality_updated_at,
               backtest_run_id, last_backtest_at, expectancy, avg_trade_pnl, median_trade_pnl,
               last_30d_return, last_90d_return, walk_forward_pass_rate, walk_forward_windows, walk_forward_summary
        FROM strategy_quality
        WHERE category=%s
    ), latest_price AS (
        SELECT DISTINCT ON (category, symbol, interval)
               category, symbol, interval, close AS last_price, start_time AS last_price_time
        FROM candles
        WHERE category=%s
        ORDER BY category, symbol, interval, start_time DESC
    ), latest_llm AS (
        SELECT DISTINCT ON (signal_id)
               signal_id, status AS llm_status, brief AS llm_brief, error AS llm_error,
               model AS llm_model, updated_at AS llm_updated_at, duration_ms AS llm_duration_ms,
               payload_hash AS llm_payload_hash
        FROM llm_evaluations
        ORDER BY signal_id, updated_at DESC
    ), latest_outcome AS (
        SELECT DISTINCT ON (signal_id)
               signal_id, evaluated_at AS outcome_evaluated_at, outcome_status, realized_r,
               max_favorable_excursion_r, max_adverse_excursion_r, exit_price, exit_time, notes AS outcome_notes
        FROM recommendation_outcomes
        ORDER BY signal_id, evaluated_at DESC
    ), outcome_ranked AS (
        SELECT s2.category, s2.symbol, s2.interval, s2.strategy, s2.direction,
               ro.outcome_status, ro.realized_r, ro.evaluated_at,
               ROW_NUMBER() OVER (
                   PARTITION BY s2.category, s2.symbol, s2.interval, s2.strategy, s2.direction
                   ORDER BY ro.evaluated_at DESC, ro.id DESC
               ) AS rn
        FROM recommendation_outcomes ro
        JOIN signals s2 ON s2.id = ro.signal_id
        WHERE ro.outcome_status <> 'open'
          AND s2.direction IN ('long','short')
    ), outcome_quality AS (
        SELECT category, symbol, interval, strategy, direction,
               COUNT(*)::int AS recent_outcomes_count,
               COUNT(*) FILTER (WHERE COALESCE(realized_r, 0) < 0)::int AS recent_loss_count,
               (COUNT(*) FILTER (WHERE COALESCE(realized_r, 0) < 0)::float / NULLIF(COUNT(*)::float, 0)) AS recent_loss_rate,
               AVG(realized_r)::float AS recent_average_r,
               (SUM(GREATEST(COALESCE(realized_r, 0), 0))::float / NULLIF(ABS(SUM(LEAST(COALESCE(realized_r, 0), 0)))::float, 0)) AS recent_profit_factor,
               CASE
                   WHEN MIN(CASE WHEN COALESCE(realized_r, 0) >= 0 THEN rn END) IS NULL THEN COUNT(*)::int
                   ELSE GREATEST(MIN(CASE WHEN COALESCE(realized_r, 0) >= 0 THEN rn END) - 1, 0)::int
               END AS recent_consecutive_losses,
               MAX(evaluated_at) AS recent_last_evaluated_at
        FROM outcome_ranked
        WHERE rn <= 20
        GROUP BY category, symbol, interval, strategy, direction
    )
    SELECT s.id, s.created_at, s.bar_time, s.expires_at, s.category, s.symbol, s.interval, s.strategy, s.direction, s.confidence,
           s.entry, s.stop_loss, s.take_profit, s.atr, s.ml_probability, s.sentiment_score, s.rationale,
           b.total_return, b.max_drawdown, b.sharpe, b.win_rate, b.profit_factor, b.trades_count,
           q.quality_status, q.quality_score, q.evidence_grade, q.quality_reason, q.quality_diagnostics, q.quality_updated_at, q.backtest_run_id, q.last_backtest_at,
           q.expectancy, q.avg_trade_pnl, q.median_trade_pnl, q.last_30d_return, q.last_90d_return, q.walk_forward_pass_rate, q.walk_forward_windows, q.walk_forward_summary,
           p.last_price, p.last_price_time,
           e.llm_status, e.llm_brief, e.llm_error, e.llm_model, e.llm_updated_at, e.llm_duration_ms, e.llm_payload_hash,
           o.outcome_evaluated_at, o.outcome_status, o.realized_r, o.max_favorable_excursion_r, o.max_adverse_excursion_r, o.exit_price, o.exit_time, o.outcome_notes,
           oq.recent_outcomes_count, oq.recent_loss_count, oq.recent_loss_rate, oq.recent_average_r, oq.recent_profit_factor, oq.recent_consecutive_losses, oq.recent_last_evaluated_at,
           (
               COALESCE(s.confidence::float, 0) * 0.35
             + LEAST(GREATEST(COALESCE(q.quality_score::float, 0) / 100.0, 0), 1) * 0.20
             + CASE WHEN q.quality_status = 'APPROVED' THEN 0.10 WHEN q.quality_status = 'WATCHLIST' THEN 0.04 WHEN q.quality_status = 'REJECTED' THEN -0.20 ELSE -0.05 END
             + LEAST(GREATEST(COALESCE(b.profit_factor::float, 1) / 2.0, 0), 1) * 0.10 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
             + LEAST(GREATEST(COALESCE(b.win_rate::float, 0), 0), 1) * 0.08 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
             - LEAST(GREATEST(COALESCE(b.max_drawdown::float, 0.2), 0), 1) * 0.12
           ) AS research_score
    FROM signals s
    LEFT JOIN latest_backtests b ON b.symbol=s.symbol AND b.interval=s.interval AND b.strategy=s.strategy
    LEFT JOIN latest_quality q ON q.symbol=s.symbol AND q.interval=s.interval AND q.strategy=s.strategy
    LEFT JOIN latest_price p ON p.category=s.category AND p.symbol=s.symbol AND p.interval=s.interval
    LEFT JOIN latest_llm e ON e.signal_id=s.id
    LEFT JOIN latest_outcome o ON o.signal_id=s.id
    LEFT JOIN outcome_quality oq ON oq.category=s.category AND oq.symbol=s.symbol AND oq.interval=s.interval AND oq.strategy=s.strategy AND oq.direction=s.direction
    WHERE {where_sql}
    """


def _fetch_recommendation_row(signal_id: int, category: str | None = None) -> dict[str, Any] | None:
    where = "s.id=%s" + (" AND s.category=%s" if category else "")
    params: list[Any] = [category or settings.default_category, category or settings.default_category, category or settings.default_category, signal_id]
    if category:
        params.append(category)
    return fetch_one(_recommendation_base_sql(where) + "\nLIMIT 1", tuple(params))

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
        "recommendation_contract": _recommendation_contract_metadata(),
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
                           id, created_at, bar_time, expires_at, category, symbol, interval, strategy, direction, confidence,
                           entry, stop_loss, take_profit, atr, ml_probability, sentiment_score, rationale
                    FROM signals
                    WHERE category=%s AND interval = ANY(%s::text[]) AND created_at >= NOW() - (%s::text || ' hours')::interval
                      AND bar_time IS NOT NULL
                      AND expires_at IS NOT NULL
                      AND expires_at > NOW()
                      AND NOT EXISTS (
                          SELECT 1
                          FROM recommendation_outcomes ro
                          WHERE ro.signal_id = signals.id
                            AND ro.outcome_status <> 'open'
                      )
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
                ), latest_price AS (
                    SELECT DISTINCT ON (category, symbol, interval)
                           category, symbol, interval, close AS last_price, start_time AS last_price_time
                    FROM candles
                    WHERE category=%s AND interval = ANY(%s::text[])
                    ORDER BY category, symbol, interval, start_time DESC
                ), latest_llm AS (
                    SELECT DISTINCT ON (signal_id)
                           signal_id, status AS llm_status, brief AS llm_brief, error AS llm_error,
                           model AS llm_model, updated_at AS llm_updated_at, duration_ms AS llm_duration_ms,
                           payload_hash AS llm_payload_hash
                    FROM llm_evaluations
                    ORDER BY signal_id, updated_at DESC
                ), outcome_ranked AS (
                    SELECT s2.category, s2.symbol, s2.interval, s2.strategy, s2.direction,
                           ro.outcome_status, ro.realized_r, ro.evaluated_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY s2.category, s2.symbol, s2.interval, s2.strategy, s2.direction
                               ORDER BY ro.evaluated_at DESC, ro.id DESC
                           ) AS rn
                    FROM recommendation_outcomes ro
                    JOIN signals s2 ON s2.id = ro.signal_id
                    WHERE ro.outcome_status <> 'open'
                      AND s2.direction IN ('long','short')
                ), outcome_quality AS (
                    SELECT category, symbol, interval, strategy, direction,
                           COUNT(*)::int AS recent_outcomes_count,
                           COUNT(*) FILTER (WHERE COALESCE(realized_r, 0) < 0)::int AS recent_loss_count,
                           (COUNT(*) FILTER (WHERE COALESCE(realized_r, 0) < 0)::float / NULLIF(COUNT(*)::float, 0)) AS recent_loss_rate,
                           AVG(realized_r)::float AS recent_average_r,
                           (SUM(GREATEST(COALESCE(realized_r, 0), 0))::float / NULLIF(ABS(SUM(LEAST(COALESCE(realized_r, 0), 0)))::float, 0)) AS recent_profit_factor,
                           CASE
                               WHEN MIN(CASE WHEN COALESCE(realized_r, 0) >= 0 THEN rn END) IS NULL THEN COUNT(*)::int
                               ELSE GREATEST(MIN(CASE WHEN COALESCE(realized_r, 0) >= 0 THEN rn END) - 1, 0)::int
                           END AS recent_consecutive_losses,
                           MAX(evaluated_at) AS recent_last_evaluated_at
                    FROM outcome_ranked
                    WHERE rn <= 20
                    GROUP BY category, symbol, interval, strategy, direction
                )
                SELECT s.id, s.created_at, s.bar_time, s.expires_at, s.category, s.symbol, s.interval, s.strategy, s.direction, s.confidence,
                       s.entry, s.stop_loss, s.take_profit, s.atr, s.ml_probability, s.sentiment_score, s.rationale,
                       b.total_return, b.max_drawdown, b.sharpe, b.win_rate, b.profit_factor, b.trades_count,
                       q.quality_status, q.quality_score, q.evidence_grade, q.quality_reason, q.quality_diagnostics, q.quality_updated_at, q.backtest_run_id, q.last_backtest_at,
                       q.expectancy, q.avg_trade_pnl, q.median_trade_pnl, q.last_30d_return, q.last_90d_return, q.walk_forward_pass_rate, q.walk_forward_windows, q.walk_forward_summary,
                       m.roc_auc, m.precision_score, m.recall_score,
                       l.liquidity_score, l.spread_pct, l.turnover_24h, l.open_interest_value, l.is_eligible,
                       l.liquidity_captured_at, l.liquidity_status,
                       p.last_price, p.last_price_time,
                       e.llm_status, e.llm_brief, e.llm_error, e.llm_model, e.llm_updated_at, e.llm_duration_ms, e.llm_payload_hash,
                       oq.recent_outcomes_count, oq.recent_loss_count, oq.recent_loss_rate, oq.recent_average_r, oq.recent_profit_factor, oq.recent_consecutive_losses, oq.recent_last_evaluated_at,
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
                LEFT JOIN latest_price p ON p.category=s.category AND p.symbol=s.symbol AND p.interval=s.interval
                LEFT JOIN latest_llm e ON e.signal_id=s.id
                LEFT JOIN outcome_quality oq ON oq.category=s.category AND oq.symbol=s.symbol AND oq.interval=s.interval AND oq.strategy=s.strategy AND oq.direction=s.direction
                ORDER BY research_score DESC NULLS LAST, s.created_at DESC
                LIMIT %s
                """,
                (
                    category, context_intervals, settings.max_signal_age_hours,
                    category, context_intervals,
                    category, context_intervals, settings.ml_auto_train_ttl_hours,
                    settings.liquidity_snapshot_max_age_minutes, category,
                    category, context_intervals,
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
            rows = annotate_recommendations(consolidate_operator_queue(ensure_operator_decisions(rows), limit=limit))
            return {"ok": True, "category": category, "entry_only": entry_only, "entry_interval": settings.mtf_entry_interval, "signals": rows}
    
        try:
            ensure_strategy_quality_storage()
        except Exception:
            pass
        rows = fetch_all(
            """
            WITH latest_signals AS (
                SELECT DISTINCT ON (category, symbol, interval, strategy, direction)
                       id, created_at, bar_time, expires_at, category, symbol, interval, strategy, direction, confidence,
                       entry, stop_loss, take_profit, atr, ml_probability, sentiment_score, rationale
                FROM signals
                WHERE category=%s AND created_at >= NOW() - (%s::text || ' hours')::interval
                  AND bar_time IS NOT NULL
                  AND expires_at IS NOT NULL
                  AND expires_at > NOW()
                  AND NOT EXISTS (
                      SELECT 1
                      FROM recommendation_outcomes ro
                      WHERE ro.signal_id = signals.id
                        AND ro.outcome_status <> 'open'
                  )
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
            ), latest_price AS (
                SELECT DISTINCT ON (category, symbol, interval)
                       category, symbol, interval, close AS last_price, start_time AS last_price_time
                FROM candles
                WHERE category=%s
                ORDER BY category, symbol, interval, start_time DESC
            ), latest_llm AS (
                SELECT DISTINCT ON (signal_id)
                       signal_id, status AS llm_status, brief AS llm_brief, error AS llm_error,
                       model AS llm_model, updated_at AS llm_updated_at, duration_ms AS llm_duration_ms,
                       payload_hash AS llm_payload_hash
                FROM llm_evaluations
                ORDER BY signal_id, updated_at DESC
            ), outcome_ranked AS (
                SELECT s2.category, s2.symbol, s2.interval, s2.strategy, s2.direction,
                       ro.outcome_status, ro.realized_r, ro.evaluated_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY s2.category, s2.symbol, s2.interval, s2.strategy, s2.direction
                           ORDER BY ro.evaluated_at DESC, ro.id DESC
                       ) AS rn
                FROM recommendation_outcomes ro
                JOIN signals s2 ON s2.id = ro.signal_id
                WHERE ro.outcome_status <> 'open'
                  AND s2.direction IN ('long','short')
            ), outcome_quality AS (
                SELECT category, symbol, interval, strategy, direction,
                       COUNT(*)::int AS recent_outcomes_count,
                       COUNT(*) FILTER (WHERE COALESCE(realized_r, 0) < 0)::int AS recent_loss_count,
                       (COUNT(*) FILTER (WHERE COALESCE(realized_r, 0) < 0)::float / NULLIF(COUNT(*)::float, 0)) AS recent_loss_rate,
                       AVG(realized_r)::float AS recent_average_r,
                       (SUM(GREATEST(COALESCE(realized_r, 0), 0))::float / NULLIF(ABS(SUM(LEAST(COALESCE(realized_r, 0), 0)))::float, 0)) AS recent_profit_factor,
                       CASE
                           WHEN MIN(CASE WHEN COALESCE(realized_r, 0) >= 0 THEN rn END) IS NULL THEN COUNT(*)::int
                           ELSE GREATEST(MIN(CASE WHEN COALESCE(realized_r, 0) >= 0 THEN rn END) - 1, 0)::int
                       END AS recent_consecutive_losses,
                       MAX(evaluated_at) AS recent_last_evaluated_at
                FROM outcome_ranked
                WHERE rn <= 20
                GROUP BY category, symbol, interval, strategy, direction
            )
            SELECT s.id, s.created_at, s.bar_time, s.expires_at, s.category, s.symbol, s.interval, s.strategy, s.direction, s.confidence, s.entry, s.stop_loss, s.take_profit,
                   s.atr, s.ml_probability, s.sentiment_score, s.rationale,
                   b.total_return, b.max_drawdown, b.sharpe, b.win_rate, b.profit_factor, b.trades_count,
                   q.quality_status, q.quality_score, q.evidence_grade, q.quality_reason, q.quality_diagnostics, q.quality_updated_at, q.backtest_run_id, q.last_backtest_at,
                   q.expectancy, q.avg_trade_pnl, q.median_trade_pnl, q.last_30d_return, q.last_90d_return, q.walk_forward_pass_rate, q.walk_forward_windows, q.walk_forward_summary,
                   m.roc_auc, m.precision_score, m.recall_score,
                   l.liquidity_score, l.spread_pct, l.turnover_24h, l.open_interest_value, l.is_eligible,
                   l.liquidity_captured_at, l.liquidity_status,
                   p.last_price, p.last_price_time,
                   e.llm_status, e.llm_brief, e.llm_error, e.llm_model, e.llm_updated_at, e.llm_duration_ms, e.llm_payload_hash,
                   oq.recent_outcomes_count, oq.recent_loss_count, oq.recent_loss_rate, oq.recent_average_r, oq.recent_profit_factor, oq.recent_consecutive_losses, oq.recent_last_evaluated_at,
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
            LEFT JOIN latest_price p ON p.category=s.category AND p.symbol=s.symbol AND p.interval=s.interval
            LEFT JOIN latest_llm e ON e.signal_id=s.id
            LEFT JOIN outcome_quality oq ON oq.category=s.category AND oq.symbol=s.symbol AND oq.interval=s.interval AND oq.strategy=s.strategy AND oq.direction=s.direction
            ORDER BY research_score DESC NULLS LAST, s.created_at DESC
            LIMIT %s
            """,
            (
                category, settings.max_signal_age_hours,
                category,
                category, settings.ml_auto_train_ttl_hours,
                settings.liquidity_snapshot_max_age_minutes, category,
                category,
                category,
                settings.max_spread_pct, limit,
            ),
        )
        rows = annotate_recommendations(consolidate_operator_queue(ensure_operator_decisions(annotate_and_filter_fresh_signals(rows)), limit=limit))
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




@router.get("/instruments")
def api_instruments(category: str = settings.default_category, mode: str | None = None, limit: int = settings.universe_limit) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        bounded_limit = bounded_int(limit, "limit", 1, 200)
        items = latest_universe(category, mode or settings.symbol_mode, bounded_limit)
        if not items:
            items = [
                {"category": category, "mode": "configured", "symbol": symbol, "rank_no": idx, "liquidity_score": None, "reason": "default_symbols"}
                for idx, symbol in enumerate(settings.default_symbols[:bounded_limit], start=1)
            ]
        return {"ok": True, "category": category, "mode": mode or settings.symbol_mode, "items": items}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "category": category, "items": [], "error": _read_error(exc)}


@router.get("/quotes/latest")
def api_latest_quotes(symbols: str | None = None, category: str = settings.default_category, interval: str = settings.default_interval) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        interval = normalize_interval(interval)
        symbol_list = _symbol_csv(symbols)
        return {"ok": True, "category": category, "interval": interval, "quotes": _latest_quote_rows(category, interval, symbol_list)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "category": category, "interval": interval, "quotes": [], "error": _read_error(exc)}


def _recommendation_contract_guardrail_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    problems: list[dict[str, Any]] = []
    for item in items:
        contract = item.get("recommendation") if isinstance(item.get("recommendation"), dict) else item
        health = contract.get("contract_health") if isinstance(contract, dict) else None
        if not isinstance(health, dict):
            problems.append({"recommendation_id": item.get("id"), "code": "missing_contract_health", "level": "warn", "message": "Contract health payload is absent."})
            continue
        for problem in health.get("problems") or []:
            problems.append({"recommendation_id": item.get("id") or contract.get("recommendation_id"), **problem})
    return {
        "ok": not any(p.get("level") == "error" for p in problems),
        "errors": sum(1 for p in problems if p.get("level") == "error"),
        "warnings": sum(1 for p in problems if p.get("level") == "warn"),
        "problems": problems[:20],
    }


@router.get("/recommendations/active")
def api_active_recommendations(limit: int = 50, category: str = settings.default_category, entry_only: bool = True) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        payload = latest_signals(limit=bounded_int(limit, "limit", 1, 500), entry_only=entry_only, category=category)
        recommendations = payload.get("signals", [])
        market_state = _market_state_for_recommendations(
            payload_ok=bool(payload.get("ok")),
            recommendations=recommendations,
            error=payload.get("error"),
        )
        decision_snapshot = None if recommendations else no_trade_decision_snapshot(
            reason=market_state["explanation"],
            category=payload.get("category", category),
        )
        contract_guardrails = _recommendation_contract_guardrail_summary(recommendations)
        return {
            "ok": bool(payload.get("ok")),
            "category": payload.get("category", category),
            "entry_interval": payload.get("entry_interval", settings.mtf_entry_interval),
            "recommendations": recommendations,
            "decision_snapshot": decision_snapshot,
            "summary": {**market_state["summary"], "contract_guardrails": contract_guardrails},
            "market_state": {**market_state, "contract_guardrails": contract_guardrails},
            "empty_state": None if recommendations else market_state["explanation"],
            "error": payload.get("error"),
        }
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        error = _read_error(exc)
        market_state = _market_state_for_recommendations(payload_ok=False, recommendations=[], error=error)
        return {"ok": False, "category": category, "recommendations": [], "decision_snapshot": no_trade_decision_snapshot(reason=market_state["explanation"], category=category), "summary": market_state["summary"], "market_state": market_state, "empty_state": market_state["explanation"], "error": error}


@router.get("/recommendations/history")
def api_recommendation_history(symbol: str | None = None, category: str = settings.default_category, limit: int = 100) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        bounded_limit = bounded_int(limit, "limit", 1, 500)
        where = "s.category=%s"
        params: list[Any] = [category, category, category, category]
        if symbol:
            where += " AND s.symbol=%s"
            params.append(normalize_symbol(symbol))
        sql = _recommendation_base_sql(where) + "\nORDER BY s.created_at DESC\nLIMIT %s"
        params.append(bounded_limit)
        rows = fetch_all(sql, tuple(params))
        return {"ok": True, "category": category, "recommendations": annotate_recommendations(rows)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "category": category, "recommendations": [], "error": _read_error(exc)}


@router.post("/recommendations/evaluate-outcomes")
def api_evaluate_recommendation_outcomes(category: str = settings.default_category, limit: int = 250) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        bounded_limit = bounded_int(limit, "limit", 1, 5000)
        return {"ok": True, "category": category, "result": evaluate_due_recommendation_outcomes(category, bounded_limit)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "category": category, "result": {"evaluated": 0, "upserted": 0}, "error": _read_error(exc)}


@router.get("/recommendations/quality")
def api_recommendation_quality(category: str = settings.default_category, interval: str | None = None) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        interval_value = normalize_interval(interval) if interval else None
        interval_filter = "AND s.interval=%s" if interval_value else ""
        params: list[Any] = [category]
        if interval_value:
            params.append(interval_value)
        outcome = fetch_one(
            f"""
            SELECT COUNT(*)::int AS evaluated,
                   AVG(realized_r)::float AS average_r,
                   SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) AS winrate,
                   SUM(GREATEST(realized_r,0))::float / NULLIF(ABS(SUM(LEAST(realized_r,0)))::float,0) AS profit_factor,
                   AVG(max_favorable_excursion_r)::float AS avg_mfe_r,
                   AVG(max_adverse_excursion_r)::float AS avg_mae_r,
                   COUNT(*) FILTER (WHERE COALESCE((notes->>'ambiguous_exit')::boolean, false)
                                    OR COALESCE((notes->>'same_bar_stop_first')::boolean, false)
                                    OR notes->>'exit_reason' = 'stop_loss_same_bar_ambiguous')::int AS ambiguous_stop_first_count
            FROM recommendation_outcomes o
            JOIN signals s ON s.id=o.signal_id
            WHERE s.category=%s {interval_filter}
              AND o.outcome_status <> 'open'
            """,
            tuple(params),
        ) or {}
        evaluated = int(outcome.get("evaluated") or 0) if isinstance(outcome, dict) else 0
        ambiguous_count = int(outcome.get("ambiguous_stop_first_count") or 0) if isinstance(outcome, dict) else 0
        ambiguous_rate = ambiguous_count / evaluated if evaluated else 0.0
        statistical_confidence = "low" if evaluated < 30 else "medium" if evaluated < 100 else "high"
        assessment = {
            "evaluated": evaluated,
            "statistical_confidence": statistical_confidence,
            "sample_warning": None if evaluated >= 30 else "Историческая выборка мала: качество стратегии и качество конкретного сигнала разделяются, риск должен быть снижен.",
            "intrabar_warning": None if ambiguous_count == 0 else f"{ambiguous_count} завершённых рекомендаций ({ambiguous_rate:.1%}) имели одновременный SL/TP внутри одной OHLC-свечи и засчитаны как SL-first.",
            "intrabar_execution_model": "conservative_ohlc_stop_loss_first",
            "metric_semantics": "winrate/average_r/profit_factor описывают завершённые рекомендации; confidence_score не является вероятностью прибыли.",
        }
        return {
            "ok": True,
            "category": category,
            "interval": interval_value,
            "strategy_quality": quality_summary(category),
            "recommendation_outcomes": outcome,
            "quality_assessment": assessment,
            "recommendation_drawdown": _quality_drawdown_payload(category, interval_value),
            "outcome_status_counts": _quality_outcome_status_counts(category, interval_value),
            "segments": _quality_segment_rows(category, interval_value),
        }
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "category": category, "strategy_quality": _empty_quality_summary(), "recommendation_outcomes": {}, "error": _read_error(exc)}


@router.post("/recommendations/recalculate")
def api_recalculate_recommendations(req: SignalBuildRequest) -> dict[str, Any]:
    # Public trading contract alias for the existing signal builder. It preserves
    # `/api/signals/build` but gives the UI a recommendation-oriented command name.
    return build_signals(req)


@router.get("/recommendations/contract")
def api_recommendation_contract() -> dict[str, Any]:
    return {"ok": True, "contract": _recommendation_contract_metadata()}


@router.get("/recommendations/{signal_id}")
def api_recommendation_detail(signal_id: int, category: str = settings.default_category) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        row = _fetch_recommendation_row(int(signal_id), category)
        if not row:
            return {"ok": False, "recommendation": None, "error": "Recommendation not found"}
        return {"ok": True, "recommendation": annotate_recommendations([row])[0]}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "recommendation": None, "error": _read_error(exc)}


@router.get("/recommendations/{signal_id}/explanation")
def api_recommendation_explanation(signal_id: int, category: str = settings.default_category) -> dict[str, Any]:
    detail = api_recommendation_detail(signal_id, category)
    item = detail.get("recommendation") or {}
    return {
        "ok": bool(detail.get("ok")),
        "recommendation_id": signal_id,
        "explanation": item.get("recommendation_explanation"),
        "factors_for": item.get("factors_for", []),
        "factors_against": item.get("factors_against", []),
        "signal_breakdown": item.get("signal_breakdown", {}),
        "error": detail.get("error"),
    }


@router.get("/recommendations/{signal_id}/similar-history")
def api_recommendation_similar_history(signal_id: int, category: str = settings.default_category, limit: int = 30) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        return _similar_recommendation_history(int(signal_id), category, limit)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "recommendation_id": signal_id, "summary": {}, "items": [], "error": _read_error(exc)}


@router.post("/recommendations/{signal_id}/operator-action")
def api_recommendation_operator_action(signal_id: int, req: OperatorActionRequest, category: str = settings.default_category) -> dict[str, Any]:
    try:
        category = normalize_category(category)
        row = _fetch_recommendation_row(int(signal_id), category)
        if not row:
            return {"ok": False, "recommendation_id": signal_id, "error": "Recommendation not found"}
        annotated = annotate_recommendations([row])[0]
        contract = annotated.get("recommendation") or annotated
        payload = {
            "recommendation_status": contract.get("recommendation_status"),
            "trade_direction": contract.get("trade_direction"),
            "risk_reward": contract.get("risk_reward"),
            "net_risk_reward": contract.get("net_risk_reward"),
            "price_status": contract.get("price_status"),
            "expires_at": contract.get("expires_at"),
        }
        execute(
            """
            INSERT INTO recommendation_operator_actions(
                signal_id, action, operator_note, observed_price, recommendation_status, payload
            ) VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (int(signal_id), req.action, req.notes, req.observed_price, contract.get("recommendation_status"), payload),
        )
        if req.action == "close_invalidated":
            execute(
                """
                INSERT INTO recommendation_outcomes(
                    signal_id, outcome_status, exit_time, exit_price, realized_r,
                    max_favorable_excursion_r, max_adverse_excursion_r, bars_observed, notes
                ) VALUES (%s,'invalidated',NOW(),%s,0,0,0,0,%s)
                ON CONFLICT (signal_id) DO UPDATE SET
                    evaluated_at=NOW(), outcome_status='invalidated', exit_time=NOW(),
                    exit_price=EXCLUDED.exit_price, realized_r=0,
                    max_favorable_excursion_r=0, max_adverse_excursion_r=0,
                    notes=EXCLUDED.notes
                """,
                (int(signal_id), req.observed_price, {"source": "operator_action", "action": req.action, "note": req.notes}),
            )
        return {
            "ok": True,
            "recommendation_id": signal_id,
            "action": req.action,
            "status": _operator_action_status(req.action),
            "recommendation_status": contract.get("recommendation_status"),
        }
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "recommendation_id": signal_id, "action": req.action, "error": _read_error(exc)}


@router.get("/system/status")
def api_system_status() -> dict[str, Any]:
    payload = status()
    try:
        latest_candle = fetch_one("SELECT MAX(start_time) AS latest_candle_at FROM candles")
        latest_signal = fetch_one("SELECT MAX(created_at) AS latest_signal_at FROM signals")
        payload["data_freshness"] = {"latest_candle_at": str(latest_candle["latest_candle_at"]) if latest_candle else None, "latest_signal_at": str(latest_signal["latest_signal_at"]) if latest_signal else None}
    except Exception as exc:
        payload["data_freshness"] = {"error": _read_error(exc)}
    return payload


@router.get("/system/warnings")
def api_system_warnings(category: str = settings.default_category) -> dict[str, Any]:
    warnings: list[dict[str, str]] = []
    try:
        category = normalize_category(category)
        counts = fetch_one("SELECT COUNT(*) AS signals FROM signals WHERE category=%s", (category,)) or {"signals": 0}
        candles = fetch_one("SELECT MAX(start_time) AS latest_candle_at FROM candles WHERE category=%s", (category,)) or {}
        if int(counts.get("signals") or 0) == 0:
            warnings.append({"code": "no_signals", "level": "warn", "message": "Нет рассчитанных сигналов; запустите синхронизацию рынка и пересчёт рекомендаций."})
        if not candles.get("latest_candle_at"):
            warnings.append({"code": "no_market_data", "level": "fail", "message": "Нет исторических свечей; рекомендации должны оставаться NO_TRADE."})
        try:
            integrity = []
            # Backward-compatible fallback keeps the historic V40 audit contract available.
            # Static contract test anchor: FROM v_recommendation_integrity_audit_v40
            for audit_view in ("v_recommendation_integrity_audit_v43", "v_recommendation_integrity_audit_v40"):
                try:
                    integrity = fetch_all(
                        f"""
                        SELECT issue_code, severity, COUNT(*)::int AS count
                        FROM {audit_view}
                        WHERE category=%s
                        GROUP BY issue_code, severity
                        ORDER BY severity DESC, count DESC, issue_code
                        LIMIT 20
                        """,
                        (category,),
                    )
                    break
                except Exception:
                    continue
            for item in integrity:
                warnings.append({
                    "code": f"recommendation_integrity_{item.get('issue_code')}",
                    "level": "fail" if item.get("severity") == "error" else "warn",
                    "message": f"Integrity audit: {item.get('issue_code')} × {item.get('count')}",
                })
        except Exception:
            pass
        return {"ok": True, "category": category, "warnings": warnings}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        return {"ok": False, "category": category, "warnings": warnings, "error": _read_error(exc)}


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
