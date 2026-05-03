-- V31 safe, repeatable migration: strict generated risk metrics, terminal outcome
-- semantics and a DB-side guard for mathematically impossible recommendations.

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS risk_pct NUMERIC GENERATED ALWAYS AS (
        CASE
            WHEN direction IN ('long','short') AND entry > 0 AND stop_loss > 0
            THEN abs(entry - stop_loss) / entry
            ELSE NULL
        END
    ) STORED;

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS expected_reward_pct NUMERIC GENERATED ALWAYS AS (
        CASE
            WHEN direction IN ('long','short') AND entry > 0 AND take_profit > 0
            THEN abs(take_profit - entry) / entry
            ELSE NULL
        END
    ) STORED;

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS risk_reward NUMERIC GENERATED ALWAYS AS (
        CASE
            WHEN direction IN ('long','short') AND entry > 0 AND stop_loss > 0 AND take_profit > 0 AND abs(entry - stop_loss) > 0
            THEN abs(take_profit - entry) / abs(entry - stop_loss)
            ELSE NULL
        END
    ) STORED;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_generated_risk_metrics_v31') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_generated_risk_metrics_v31 CHECK (
            direction = 'flat'
            OR (
                risk_pct IS NOT NULL AND risk_pct > 0
                AND expected_reward_pct IS NOT NULL AND expected_reward_pct > 0
                AND risk_reward IS NOT NULL AND risk_reward > 0
            )
        ) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_outcome_terminal_fields_v31') THEN
        ALTER TABLE recommendation_outcomes ADD CONSTRAINT ck_recommendation_outcome_terminal_fields_v31 CHECK (
            (outcome_status = 'open' AND exit_time IS NULL AND exit_price IS NULL AND realized_r IS NULL)
            OR (outcome_status IN ('hit_take_profit','hit_stop_loss','closed_manual') AND exit_time IS NOT NULL AND exit_price IS NOT NULL AND realized_r IS NOT NULL)
            OR (outcome_status IN ('expired','invalidated') AND realized_r IS NOT NULL)
        ) NOT VALID;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_signal_recommendation_contract_v31()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.direction IN ('long','short') THEN
        IF NEW.category IS NULL OR btrim(NEW.category) = '' THEN
            RAISE EXCEPTION 'directional recommendation requires category';
        END IF;
        IF NEW.symbol IS NULL OR btrim(NEW.symbol) = '' THEN
            RAISE EXCEPTION 'directional recommendation requires symbol';
        END IF;
        IF NEW.interval IS NULL OR NEW.interval NOT IN ('1','3','5','15','30','60','120','240','360','720','D','W','M') THEN
            RAISE EXCEPTION 'directional recommendation has incompatible timeframe: %', NEW.interval;
        END IF;
        IF NEW.bar_time IS NULL THEN
            RAISE EXCEPTION 'directional recommendation requires bar_time';
        END IF;
        IF NEW.expires_at IS NULL OR NEW.expires_at <= NEW.bar_time THEN
            RAISE EXCEPTION 'directional recommendation requires expires_at after bar_time';
        END IF;
        IF NEW.confidence IS NULL OR NEW.confidence < 0 OR NEW.confidence > 1 THEN
            RAISE EXCEPTION 'directional recommendation confidence must be in [0,1]';
        END IF;
        IF NEW.entry IS NULL OR NEW.stop_loss IS NULL OR NEW.take_profit IS NULL OR NEW.atr IS NULL THEN
            RAISE EXCEPTION 'directional recommendation requires entry, stop_loss, take_profit and atr';
        END IF;
        IF NEW.entry <= 0 OR NEW.stop_loss <= 0 OR NEW.take_profit <= 0 OR NEW.atr <= 0 THEN
            RAISE EXCEPTION 'directional recommendation levels and atr must be positive';
        END IF;
        IF NEW.direction = 'long' AND NOT (NEW.stop_loss < NEW.entry AND NEW.entry < NEW.take_profit) THEN
            RAISE EXCEPTION 'invalid LONG levels: require stop_loss < entry < take_profit';
        END IF;
        IF NEW.direction = 'short' AND NOT (NEW.take_profit < NEW.entry AND NEW.entry < NEW.stop_loss) THEN
            RAISE EXCEPTION 'invalid SHORT levels: require take_profit < entry < stop_loss';
        END IF;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_enforce_signal_recommendation_contract_v31 ON signals;
CREATE TRIGGER trg_enforce_signal_recommendation_contract_v31
BEFORE INSERT OR UPDATE ON signals
FOR EACH ROW
EXECUTE FUNCTION enforce_signal_recommendation_contract_v31();

CREATE INDEX IF NOT EXISTS idx_signals_active_contract_v31
ON signals(category, symbol, interval, expires_at DESC, confidence DESC)
WHERE direction IN ('long','short') AND bar_time IS NOT NULL AND expires_at IS NOT NULL;

CREATE OR REPLACE VIEW v_recommendation_quality_summary AS
SELECT s.category,
       s.symbol,
       s.interval,
       s.strategy,
       COUNT(*)::int AS evaluated,
       AVG(o.realized_r)::float AS average_r,
       SUM(CASE WHEN o.realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS winrate,
       SUM(GREATEST(o.realized_r, 0))::float / NULLIF(ABS(SUM(LEAST(o.realized_r, 0)))::float, 0) AS profit_factor,
       AVG(o.max_favorable_excursion_r)::float AS avg_mfe_r,
       AVG(o.max_adverse_excursion_r)::float AS avg_mae_r
FROM recommendation_outcomes o
JOIN signals s ON s.id = o.signal_id
WHERE o.outcome_status <> 'open'
GROUP BY s.category, s.symbol, s.interval, s.strategy;
