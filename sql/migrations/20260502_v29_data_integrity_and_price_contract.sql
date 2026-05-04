-- V29: market-data integrity and stored recommendation TTL.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_candles_positive_ohlcv') THEN
        ALTER TABLE candles ADD CONSTRAINT ck_candles_positive_ohlcv CHECK (
            open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
            AND high >= GREATEST(open, close, low)
            AND low <= LEAST(open, close, high)
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_candles_valid_bybit_interval') THEN
        ALTER TABLE candles ADD CONSTRAINT ck_candles_valid_bybit_interval CHECK (interval IN ('1','3','5','15','30','60','120','240','360','720','D','W','M')) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_liquidity_non_negative_metrics') THEN
        ALTER TABLE liquidity_snapshots ADD CONSTRAINT ck_liquidity_non_negative_metrics CHECK (
            (turnover_24h IS NULL OR turnover_24h >= 0)
            AND (volume_24h IS NULL OR volume_24h >= 0)
            AND (open_interest_value IS NULL OR open_interest_value >= 0)
            AND (spread_pct IS NULL OR spread_pct >= 0)
            AND (liquidity_score >= 0)
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_strategy_quality_scores_ranges') THEN
        ALTER TABLE strategy_quality ADD CONSTRAINT ck_strategy_quality_scores_ranges CHECK (
            quality_score >= 0 AND quality_score <= 100
            AND trades_count >= 0
            AND (win_rate IS NULL OR (win_rate >= 0 AND win_rate <= 1))
            AND (profit_factor IS NULL OR profit_factor >= 0)
            AND (walk_forward_pass_rate IS NULL OR (walk_forward_pass_rate >= 0 AND walk_forward_pass_rate <= 1))
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_expires_after_bar') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_expires_after_bar CHECK (
            direction = 'flat' OR (bar_time IS NOT NULL AND expires_at IS NOT NULL AND expires_at > bar_time)
        ) NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_signals_expires_at
ON signals(category, expires_at DESC, symbol, interval)
WHERE expires_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_quality_cube
ON recommendation_outcomes(outcome_status, evaluated_at DESC, signal_id);
