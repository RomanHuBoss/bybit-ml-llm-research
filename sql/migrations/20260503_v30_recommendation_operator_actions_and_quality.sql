-- V30: operator action audit trail, stricter numeric hygiene and quality segmentation indexes.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_non_empty_identity') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_non_empty_identity CHECK (
            btrim(category) <> '' AND btrim(symbol) <> '' AND btrim(interval) <> '' AND btrim(strategy) <> ''
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_no_numeric_nan') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_no_numeric_nan CHECK (
            confidence::text <> 'NaN'
            AND (entry IS NULL OR entry::text <> 'NaN')
            AND (stop_loss IS NULL OR stop_loss::text <> 'NaN')
            AND (take_profit IS NULL OR take_profit::text <> 'NaN')
            AND (atr IS NULL OR atr::text <> 'NaN')
            AND (ml_probability IS NULL OR ml_probability::text <> 'NaN')
            AND (sentiment_score IS NULL OR sentiment_score::text <> 'NaN')
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_backtest_metric_ranges_v30') THEN
        ALTER TABLE backtest_runs ADD CONSTRAINT ck_backtest_metric_ranges_v30 CHECK (
            initial_equity > 0 AND final_equity >= 0
            AND max_drawdown >= 0
            AND trades_count >= 0
            AND (win_rate IS NULL OR (win_rate >= 0 AND win_rate <= 1))
            AND (profit_factor IS NULL OR profit_factor >= 0)
        ) NOT VALID;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS recommendation_operator_actions (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action TEXT NOT NULL CHECK (action IN ('skip','wait_confirmation','manual_review','close_invalidated','paper_opened')),
    operator_note TEXT,
    observed_price NUMERIC CHECK (observed_price IS NULL OR observed_price > 0),
    recommendation_status TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_recommendation_operator_actions_signal
ON recommendation_operator_actions(signal_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_recommendation_operator_actions_action_time
ON recommendation_operator_actions(action, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_signals_quality_segments_v30
ON signals(category, symbol, interval, strategy, confidence, created_at DESC);
