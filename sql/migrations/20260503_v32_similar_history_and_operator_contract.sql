-- V32: similar-signal outcome history and stricter operator-action contract.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_operator_actions_status_v32') THEN
        ALTER TABLE recommendation_operator_actions ADD CONSTRAINT ck_recommendation_operator_actions_status_v32 CHECK (
            recommendation_status IS NULL OR recommendation_status IN (
                'review_entry','research_candidate','wait','blocked','expired','invalid','missed_entry'
            )
        ) NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_signals_similarity_lookup_v32
ON signals(category, symbol, interval, strategy, direction, bar_time DESC)
WHERE direction IN ('long','short') AND bar_time IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_terminal_v32
ON recommendation_outcomes(outcome_status, evaluated_at DESC, signal_id)
WHERE outcome_status <> 'open';

CREATE OR REPLACE VIEW v_recommendation_similar_history AS
SELECT s.category,
       s.symbol,
       s.interval,
       s.strategy,
       s.direction,
       s.id AS signal_id,
       s.bar_time,
       s.confidence,
       s.entry,
       s.stop_loss,
       s.take_profit,
       s.risk_reward,
       o.outcome_status,
       o.exit_time,
       o.exit_price,
       o.realized_r,
       o.max_favorable_excursion_r,
       o.max_adverse_excursion_r,
       o.bars_observed,
       o.evaluated_at
FROM recommendation_outcomes o
JOIN signals s ON s.id = o.signal_id
WHERE o.outcome_status <> 'open';
