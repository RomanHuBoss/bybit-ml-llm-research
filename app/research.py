from __future__ import annotations

from typing import Any

from .config import settings
from .db import fetch_all
from .mtf import apply_mtf_consensus
from .recommendation import annotate_recommendations
from .safety import annotate_and_filter_fresh_signals


def _unique_intervals(values: list[str] | tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for value in values:
        interval = str(value).strip().upper()
        if interval and interval not in out:
            out.append(interval)
    return out


def _mtf_role_intervals() -> list[str]:
    return _unique_intervals([settings.mtf_entry_interval, settings.mtf_bias_interval, settings.mtf_regime_interval])


def rank_candidates(category: str = "linear", interval: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    selected_interval = interval or (settings.mtf_entry_interval if settings.mtf_consensus_enabled else settings.default_interval)
    return rank_candidates_multi(category, [selected_interval], limit)


def rank_candidates_multi(category: str = "linear", intervals: list[str] | tuple[str, ...] = ("60",), limit: int = 30) -> list[dict[str, Any]]:
    requested_intervals = _unique_intervals([str(interval).strip().upper() for interval in intervals if str(interval).strip()])
    if not requested_intervals:
        return []

    entry_interval = str(settings.mtf_entry_interval).strip().upper()
    requested_entry_queue = entry_interval in requested_intervals

    # MTF-контекст требует старшие TF для расчета bias/regime, но это не означает,
    # что 60m/240m должны попадать в очередь торговых рекомендаций. Они загружаются
    # только как контекст для 15m entry-кандидата.
    if settings.mtf_consensus_enabled and requested_entry_queue:
        query_intervals = _unique_intervals(requested_intervals + _mtf_role_intervals())
    else:
        query_intervals = requested_intervals

    query_limit = max(limit * 8, limit, 60)
    rows = fetch_all(
        """
        WITH latest_signals AS (
            SELECT DISTINCT ON (symbol, interval, strategy, direction)
                   id, created_at, bar_time, category, symbol, interval, strategy, direction, confidence,
                   entry, stop_loss, take_profit, ml_probability, sentiment_score, rationale
            FROM signals
            WHERE category=%s AND interval = ANY(%s) AND created_at >= NOW() - (%s::text || ' hours')::interval
              AND bar_time IS NOT NULL
            ORDER BY symbol, interval, strategy, direction, created_at DESC
        ), latest_backtests AS (
            SELECT DISTINCT ON (symbol, interval, strategy)
                   symbol, interval, strategy, total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count, created_at
            FROM backtest_runs
            WHERE category=%s AND interval = ANY(%s)
            ORDER BY symbol, interval, strategy, created_at DESC
        ), latest_models AS (
            SELECT DISTINCT ON (symbol, interval)
                   symbol, interval, roc_auc, precision_score, recall_score, created_at
            FROM model_runs
            WHERE category=%s AND interval = ANY(%s)
              AND created_at >= NOW() - (%s::text || ' hours')::interval
            ORDER BY symbol, interval, created_at DESC
        ), latest_liq_time AS (
            SELECT MAX(captured_at) AS captured_at FROM liquidity_snapshots WHERE category=%s
        ), latest_liq AS (
            SELECT l.symbol, l.liquidity_score, l.spread_pct, l.turnover_24h, l.open_interest_value, l.is_eligible
            FROM liquidity_snapshots l
            JOIN latest_liq_time t ON t.captured_at = l.captured_at
            WHERE l.category=%s
        ), latest_llm AS (
            SELECT DISTINCT ON (signal_id)
                   signal_id, status AS llm_status, brief AS llm_brief, error AS llm_error,
                   model AS llm_model, updated_at AS llm_updated_at, duration_ms AS llm_duration_ms,
                   payload_hash AS llm_payload_hash
            FROM llm_evaluations
            ORDER BY signal_id, updated_at DESC
        )
        SELECT s.id, s.created_at, s.bar_time, s.symbol, s.interval, s.strategy, s.direction, s.confidence,
               s.entry, s.stop_loss, s.take_profit, s.ml_probability, s.sentiment_score, s.rationale,
               b.total_return, b.max_drawdown, b.sharpe, b.win_rate, b.profit_factor, b.trades_count,
               m.roc_auc, m.precision_score, m.recall_score,
               l.liquidity_score, l.spread_pct, l.turnover_24h, l.open_interest_value, l.is_eligible,
               e.llm_status, e.llm_brief, e.llm_error, e.llm_model, e.llm_updated_at, e.llm_duration_ms, e.llm_payload_hash,
               (
                   COALESCE(s.confidence::float, 0) * 0.30
                 + LEAST(GREATEST(COALESCE(b.profit_factor::float, 1) / 2.0, 0), 1) * 0.14 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
                 + LEAST(GREATEST(COALESCE(b.sharpe::float, 0) / 3.0, 0), 1) * 0.10 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
                 + LEAST(GREATEST(COALESCE(b.win_rate::float, 0), 0), 1) * 0.08 * LEAST(GREATEST(COALESCE(b.trades_count::float, 0) / 50.0, 0), 1)
                 + LEAST(GREATEST((COALESCE(m.roc_auc::float, 0.5) - 0.5) / 0.25, 0), 1) * 0.15
                 + LEAST(GREATEST(COALESCE(l.liquidity_score::float, 0) / 8.0, 0), 1) * 0.10
                 + CASE WHEN COALESCE(l.is_eligible, FALSE) THEN 0.05 ELSE -0.10 END
                 + CASE WHEN COALESCE(l.spread_pct::float, 999) <= %s THEN 0.05 ELSE -0.05 END
                 - LEAST(GREATEST(COALESCE(b.max_drawdown::float, 0.2), 0), 1) * 0.10
               ) AS research_score
        FROM latest_signals s
        LEFT JOIN latest_backtests b ON b.symbol=s.symbol AND b.interval=s.interval AND b.strategy=s.strategy
        LEFT JOIN latest_models m ON m.symbol=s.symbol AND m.interval=s.interval
        LEFT JOIN latest_liq l ON l.symbol=s.symbol
        LEFT JOIN latest_llm e ON e.signal_id=s.id
        ORDER BY research_score DESC NULLS LAST, s.created_at DESC
        LIMIT %s
        """,
        (
            category,
            query_intervals,
            settings.max_signal_age_hours,
            category,
            query_intervals,
            category,
            query_intervals,
            settings.ml_auto_train_ttl_hours,
            category,
            category,
            settings.max_spread_pct,
            query_limit,
        ),
    )
    rows = annotate_and_filter_fresh_signals(rows)
    if settings.mtf_consensus_enabled:
        rows = apply_mtf_consensus(
            rows,
            entry_interval=settings.mtf_entry_interval,
            bias_interval=settings.mtf_bias_interval,
            regime_interval=settings.mtf_regime_interval,
        )
        # В operator queue возвращаются только реальные entry-кандидаты. 60m/240m
        # остаются внутри mtf_entry/mtf_bias/mtf_regime и больше не выглядят как
        # самостоятельные рекомендации на сделку.
        if not requested_entry_queue:
            return []
        rows = [row for row in rows if str(row.get("interval") or "").strip().upper() == entry_interval]
    return annotate_recommendations(rows[:limit])
