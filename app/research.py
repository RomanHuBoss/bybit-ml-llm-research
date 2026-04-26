from __future__ import annotations

from typing import Any

from .config import settings
from .db import fetch_all


def rank_candidates(category: str = "linear", interval: str = "60", limit: int = 30) -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        WITH latest_signals AS (
            SELECT DISTINCT ON (symbol, strategy, direction)
                   id, created_at, bar_time, category, symbol, interval, strategy, direction, confidence,
                   entry, stop_loss, take_profit, sentiment_score, rationale
            FROM signals
            WHERE category=%s AND interval=%s AND created_at >= NOW() - (%s::text || ' hours')::interval
            ORDER BY symbol, strategy, direction, created_at DESC
        ), latest_backtests AS (
            SELECT DISTINCT ON (symbol, strategy)
                   symbol, strategy, total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count, created_at
            FROM backtest_runs
            WHERE category=%s AND interval=%s
            ORDER BY symbol, strategy, created_at DESC
        ), latest_models AS (
            SELECT DISTINCT ON (symbol)
                   symbol, roc_auc, precision_score, recall_score, created_at
            FROM model_runs
            WHERE category=%s AND interval=%s
            ORDER BY symbol, created_at DESC
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
               s.entry, s.stop_loss, s.take_profit, s.sentiment_score, s.rationale,
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
        LEFT JOIN latest_backtests b ON b.symbol=s.symbol AND b.strategy=s.strategy
        LEFT JOIN latest_models m ON m.symbol=s.symbol
        LEFT JOIN latest_liq l ON l.symbol=s.symbol
        LEFT JOIN latest_llm e ON e.signal_id=s.id
        ORDER BY research_score DESC NULLS LAST, s.created_at DESC
        LIMIT %s
        """,
        (
            category,
            interval,
            settings.max_signal_age_hours,
            category,
            interval,
            category,
            interval,
            category,
            category,
            settings.max_spread_pct,
            limit,
        ),
    )
    return rows
