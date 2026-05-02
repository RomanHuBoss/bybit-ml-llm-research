-- V28: canonical recommendation contract and outcome lifecycle hardening.
-- This migration is safe to re-run. Constraints are added as NOT VALID so legacy
-- rows can be audited separately, while every new/updated row is protected.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_confidence_0_1') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_confidence_0_1 CHECK (confidence >= 0 AND confidence <= 1) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_ml_probability_0_1') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_ml_probability_0_1 CHECK (ml_probability IS NULL OR (ml_probability >= 0 AND ml_probability <= 1)) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_positive_trade_levels') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_positive_trade_levels CHECK (
            direction = 'flat'
            OR (entry > 0 AND stop_loss > 0 AND take_profit > 0 AND atr > 0)
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_level_side_matches_direction') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_level_side_matches_direction CHECK (
            direction = 'flat'
            OR (direction = 'long' AND stop_loss < entry AND entry < take_profit)
            OR (direction = 'short' AND take_profit < entry AND entry < stop_loss)
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_has_market_timestamp_for_trade') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_has_market_timestamp_for_trade CHECK (direction = 'flat' OR bar_time IS NOT NULL) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_valid_bybit_interval') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_valid_bybit_interval CHECK (interval IN ('1','3','5','15','30','60','120','240','360','720','D','W','M')) NOT VALID;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS recommendation_outcomes (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome_status TEXT NOT NULL CHECK (outcome_status IN ('open','hit_take_profit','hit_stop_loss','expired','invalidated','closed_manual')),
    exit_time TIMESTAMPTZ,
    exit_price NUMERIC,
    realized_r NUMERIC,
    max_favorable_excursion_r NUMERIC,
    max_adverse_excursion_r NUMERIC,
    bars_observed INTEGER NOT NULL DEFAULT 0 CHECK (bars_observed >= 0),
    notes JSONB,
    UNIQUE(signal_id),
    CHECK (exit_price IS NULL OR exit_price > 0),
    CHECK (realized_r IS NULL OR (realized_r >= -1000 AND realized_r <= 1000)),
    CHECK (max_favorable_excursion_r IS NULL OR max_favorable_excursion_r >= 0),
    CHECK (max_adverse_excursion_r IS NULL OR max_adverse_excursion_r <= 0)
);

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_status
ON recommendation_outcomes(outcome_status, evaluated_at DESC);

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_signal
ON recommendation_outcomes(signal_id, evaluated_at DESC);

CREATE INDEX IF NOT EXISTS idx_signals_active_recommendations
ON signals(category, interval, created_at DESC, symbol, strategy)
WHERE direction IN ('long','short') AND bar_time IS NOT NULL;
