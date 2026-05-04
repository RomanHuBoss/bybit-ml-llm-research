-- V35: active recommendation integrity and terminal-outcome separation.
-- Safe to re-run. Active recommendation queries must not resurrect signals that
-- already have a terminal outcome, and quality statistics must be based on
-- completed recommendations rather than open rows.

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_terminal_v35
ON recommendation_outcomes(signal_id, evaluated_at DESC)
WHERE outcome_status <> 'open';

CREATE INDEX IF NOT EXISTS idx_signals_active_contract_v35
ON signals(category, interval, expires_at DESC, symbol, strategy, confidence DESC)
WHERE direction IN ('long','short')
  AND bar_time IS NOT NULL
  AND expires_at IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_outcomes_terminal_price_v35') THEN
        ALTER TABLE recommendation_outcomes ADD CONSTRAINT ck_recommendation_outcomes_terminal_price_v35 CHECK (
            outcome_status = 'open'
            OR (
                outcome_status IN ('hit_take_profit','hit_stop_loss','closed_manual')
                AND exit_time IS NOT NULL
                AND exit_price IS NOT NULL
                AND exit_price > 0
                AND realized_r IS NOT NULL
            )
            OR (
                outcome_status IN ('expired','invalidated')
                AND realized_r IS NOT NULL
            )
        ) NOT VALID;
    END IF;
END $$;

CREATE OR REPLACE VIEW v_active_recommendation_contract_v35 AS
SELECT s.*
FROM signals s
WHERE s.direction IN ('long','short')
  AND s.bar_time IS NOT NULL
  AND s.expires_at IS NOT NULL
  AND s.expires_at > NOW()
  AND NOT EXISTS (
      SELECT 1
      FROM recommendation_outcomes o
      WHERE o.signal_id = s.id
        AND o.outcome_status <> 'open'
  );

CREATE OR REPLACE VIEW v_recommendation_quality_terminal_v35 AS
SELECT s.category,
       s.symbol,
       s.interval,
       s.strategy,
       s.direction,
       COUNT(*)::int AS evaluated,
       AVG(o.realized_r)::float AS average_r,
       SUM(CASE WHEN o.realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS winrate,
       SUM(GREATEST(o.realized_r, 0))::float / NULLIF(ABS(SUM(LEAST(o.realized_r, 0)))::float, 0) AS profit_factor,
       AVG(o.max_favorable_excursion_r)::float AS avg_mfe_r,
       AVG(o.max_adverse_excursion_r)::float AS avg_mae_r,
       MAX(o.evaluated_at) AS last_evaluated_at
FROM recommendation_outcomes o
JOIN signals s ON s.id = o.signal_id
WHERE o.outcome_status <> 'open'
GROUP BY s.category, s.symbol, s.interval, s.strategy, s.direction;
