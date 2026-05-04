-- V42 Intrabar SL/TP ambiguity guardrails
-- Safe to run more than once.
-- Fix scope: бэктест и outcome-аналитика должны явно маркировать свечи,
-- где SL и TP достижимы внутри одной OHLC-свечи. Без tick/order-book порядка
-- система использует консервативную модель SL-first.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_backtest_trades_reason_v42
ON backtest_trades(run_id, reason);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_backtest_trades_reason_v42') THEN
        ALTER TABLE backtest_trades
        ADD CONSTRAINT chk_backtest_trades_reason_v42
        CHECK (reason IS NULL OR btrim(reason) <> '') NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_ambiguous_v42
ON recommendation_outcomes(signal_id, evaluated_at DESC)
WHERE COALESCE((notes->>'ambiguous_exit')::boolean, false)
   OR COALESCE((notes->>'same_bar_stop_first')::boolean, false)
   OR notes->>'exit_reason' = 'stop_loss_same_bar_ambiguous';

CREATE OR REPLACE VIEW v_intrabar_execution_quality_v42 AS
SELECT
    s.category,
    s.symbol,
    s.interval,
    s.strategy,
    COUNT(*)::int AS evaluated_outcomes,
    COUNT(*) FILTER (
        WHERE COALESCE((o.notes->>'ambiguous_exit')::boolean, false)
           OR COALESCE((o.notes->>'same_bar_stop_first')::boolean, false)
           OR o.notes->>'exit_reason' = 'stop_loss_same_bar_ambiguous'
    )::int AS same_bar_stop_first_count,
    (
        COUNT(*) FILTER (
            WHERE COALESCE((o.notes->>'ambiguous_exit')::boolean, false)
               OR COALESCE((o.notes->>'same_bar_stop_first')::boolean, false)
               OR o.notes->>'exit_reason' = 'stop_loss_same_bar_ambiguous'
        )::numeric / NULLIF(COUNT(*), 0)
    ) AS same_bar_stop_first_rate,
    'conservative_ohlc_stop_loss_first'::text AS intrabar_execution_model
FROM recommendation_outcomes o
JOIN signals s ON s.id = o.signal_id
WHERE o.outcome_status <> 'open'
GROUP BY s.category, s.symbol, s.interval, s.strategy;

CREATE OR REPLACE VIEW v_backtest_intrabar_execution_quality_v42 AS
SELECT
    r.category,
    r.symbol,
    r.interval,
    r.strategy,
    r.id AS backtest_run_id,
    COUNT(t.id)::int AS trades_count,
    COUNT(t.id) FILTER (WHERE t.reason = 'stop_loss_same_bar_ambiguous')::int AS same_bar_stop_first_count,
    COUNT(t.id) FILTER (WHERE t.reason = 'stop_loss_same_bar_ambiguous')::numeric / NULLIF(COUNT(t.id), 0) AS same_bar_stop_first_rate,
    COALESCE(r.params->>'intrabar_execution_model', 'conservative_ohlc_stop_loss_first') AS intrabar_execution_model
FROM backtest_runs r
LEFT JOIN backtest_trades t ON t.run_id = r.id
GROUP BY r.category, r.symbol, r.interval, r.strategy, r.id, r.params;

COMMIT;
