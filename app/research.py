from __future__ import annotations

from typing import Any

from .db import fetch_all


def rank_candidates(category: str = "linear", interval: str = "60", limit: int = 30) -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        WITH latest_backtests AS (
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
            SELECT l.symbol, l.liquidity_score, l.spread_pct, l.turnover_24h, l.open_interest_value
            FROM liquidity_snapshots l
            JOIN latest_liq_time t ON t.captured_at = l.captured_at
            WHERE l.category=%s
        )
        SELECT s.id, s.created_at, s.symbol, s.interval, s.strategy, s.direction, s.confidence,
               s.entry, s.stop_loss, s.take_profit, s.sentiment_score, s.rationale,
               b.total_return, b.max_drawdown, b.sharpe, b.win_rate, b.profit_factor, b.trades_count,
               m.roc_auc, m.precision_score, m.recall_score,
               l.liquidity_score, l.spread_pct, l.turnover_24h, l.open_interest_value,
               (
                   COALESCE(s.confidence::float, 0) * 0.30
                 + LEAST(GREATEST(COALESCE(b.profit_factor::float, 1) / 2.0, 0), 1) * 0.18
                 + LEAST(GREATEST(COALESCE(b.sharpe::float, 0) / 3.0, 0), 1) * 0.12
                 + LEAST(GREATEST(COALESCE(b.win_rate::float, 0), 0), 1) * 0.10
                 + LEAST(GREATEST(COALESCE(m.roc_auc::float, 0.5) - 0.5, 0), 0.25) * 1.2 * 0.15
                 + LEAST(GREATEST(COALESCE(l.liquidity_score::float, 0) / 8.0, 0), 1) * 0.10
                 + CASE WHEN COALESCE(l.spread_pct::float, 0.05) <= 0.05 THEN 0.05 ELSE 0 END
                 - LEAST(GREATEST(COALESCE(b.max_drawdown::float, 0.2), 0), 1) * 0.10
               ) AS research_score
        FROM signals s
        LEFT JOIN latest_backtests b ON b.symbol=s.symbol AND b.strategy=s.strategy
        LEFT JOIN latest_models m ON m.symbol=s.symbol
        LEFT JOIN latest_liq l ON l.symbol=s.symbol
        WHERE s.category=%s AND s.interval=%s
        ORDER BY research_score DESC NULLS LAST, s.created_at DESC
        LIMIT %s
        """,
        (category, interval, category, interval, category, category, category, interval, limit),
    )
    return rows
