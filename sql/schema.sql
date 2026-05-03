CREATE TABLE IF NOT EXISTS candles (
    id BIGSERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    open NUMERIC NOT NULL,
    high NUMERIC NOT NULL,
    low NUMERIC NOT NULL,
    close NUMERIC NOT NULL,
    volume NUMERIC NOT NULL,
    turnover NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(category, symbol, interval, start_time)
);

CREATE INDEX IF NOT EXISTS idx_candles_symbol_interval_time
ON candles(symbol, interval, start_time DESC);

CREATE TABLE IF NOT EXISTS funding_rates (
    id BIGSERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    symbol TEXT NOT NULL,
    funding_time TIMESTAMPTZ NOT NULL,
    funding_rate NUMERIC NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(category, symbol, funding_time)
);

CREATE INDEX IF NOT EXISTS idx_funding_symbol_time
ON funding_rates(symbol, funding_time DESC);

CREATE TABLE IF NOT EXISTS open_interest (
    id BIGSERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval_time TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open_interest NUMERIC NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(category, symbol, interval_time, ts)
);

CREATE INDEX IF NOT EXISTS idx_oi_symbol_time
ON open_interest(symbol, ts DESC);

CREATE TABLE IF NOT EXISTS liquidity_snapshots (
    id BIGSERIAL PRIMARY KEY,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT NOT NULL,
    symbol TEXT NOT NULL,
    turnover_24h NUMERIC,
    volume_24h NUMERIC,
    open_interest_value NUMERIC,
    bid1_price NUMERIC,
    ask1_price NUMERIC,
    last_price NUMERIC,
    spread_pct NUMERIC,
    funding_rate NUMERIC,
    listing_age_days INTEGER,
    liquidity_score NUMERIC NOT NULL DEFAULT 0,
    is_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    raw_json JSONB,
    UNIQUE(category, symbol, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_liquidity_latest
ON liquidity_snapshots(category, captured_at DESC, liquidity_score DESC);

CREATE TABLE IF NOT EXISTS symbol_universe (
    id BIGSERIAL PRIMARY KEY,
    selected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT NOT NULL,
    mode TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rank_no INTEGER NOT NULL,
    liquidity_score NUMERIC NOT NULL,
    reason TEXT,
    components JSONB,
    UNIQUE(category, mode, symbol, selected_at)
);

CREATE INDEX IF NOT EXISTS idx_symbol_universe_latest
ON symbol_universe(category, selected_at DESC, rank_no);

CREATE TABLE IF NOT EXISTS sentiment_daily (
    id BIGSERIAL PRIMARY KEY,
    day DATE NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT 'MARKET',
    score NUMERIC NOT NULL,
    label TEXT,
    raw_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(day, source, symbol)
);

CREATE INDEX IF NOT EXISTS idx_sentiment_day_source
ON sentiment_daily(day DESC, source, symbol);

CREATE TABLE IF NOT EXISTS sentiment_intraday (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT 'MARKET',
    interval TEXT NOT NULL DEFAULT '60',
    score NUMERIC NOT NULL,
    label TEXT,
    components JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(ts, source, symbol, interval)
);

CREATE INDEX IF NOT EXISTS idx_sentiment_intraday_symbol_time
ON sentiment_intraday(symbol, ts DESC, source);

CREATE TABLE IF NOT EXISTS news_items (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT 'MARKET',
    published_at TIMESTAMPTZ,
    title TEXT NOT NULL,
    url TEXT,
    source_domain TEXT,
    sentiment_score NUMERIC,
    llm_score NUMERIC,
    llm_label TEXT,
    raw_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source, url)
);

CREATE INDEX IF NOT EXISTS idx_news_symbol_time
ON news_items(symbol, published_at DESC);

CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    strategy TEXT NOT NULL,
    bar_time TIMESTAMPTZ,
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short', 'flat')),
    confidence NUMERIC NOT NULL,
    entry NUMERIC,
    stop_loss NUMERIC,
    take_profit NUMERIC,
    atr NUMERIC,
    ml_probability NUMERIC,
    sentiment_score NUMERIC,
    rationale JSONB
);

ALTER TABLE signals ADD COLUMN IF NOT EXISTS bar_time TIMESTAMPTZ;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_signals_created
ON signals(created_at DESC, symbol, strategy);

CREATE UNIQUE INDEX IF NOT EXISTS ux_signals_bar_dedup
ON signals(category, symbol, interval, strategy, direction, bar_time)
WHERE bar_time IS NOT NULL;

CREATE TABLE IF NOT EXISTS backtest_runs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    strategy TEXT NOT NULL,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    initial_equity NUMERIC NOT NULL,
    final_equity NUMERIC NOT NULL,
    total_return NUMERIC NOT NULL,
    max_drawdown NUMERIC NOT NULL,
    sharpe NUMERIC,
    win_rate NUMERIC,
    profit_factor NUMERIC,
    trades_count INTEGER NOT NULL,
    params JSONB,
    equity_curve JSONB
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_lookup
ON backtest_runs(category, interval, symbol, strategy, created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ NOT NULL,
    entry NUMERIC NOT NULL,
    exit NUMERIC NOT NULL,
    pnl NUMERIC NOT NULL,
    pnl_pct NUMERIC NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
ON backtest_trades(run_id);


CREATE TABLE IF NOT EXISTS strategy_quality (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    strategy TEXT NOT NULL,
    quality_status TEXT NOT NULL CHECK (quality_status IN ('APPROVED','WATCHLIST','RESEARCH','REJECTED','STALE')),
    quality_score NUMERIC NOT NULL DEFAULT 0,
    evidence_grade TEXT NOT NULL DEFAULT 'INSUFFICIENT',
    quality_reason TEXT,
    backtest_run_id BIGINT REFERENCES backtest_runs(id) ON DELETE SET NULL,
    last_backtest_at TIMESTAMPTZ,
    total_return NUMERIC,
    max_drawdown NUMERIC,
    sharpe NUMERIC,
    win_rate NUMERIC,
    profit_factor NUMERIC,
    trades_count INTEGER NOT NULL DEFAULT 0,
    expectancy NUMERIC,
    avg_trade_pnl NUMERIC,
    median_trade_pnl NUMERIC,
    last_30d_return NUMERIC,
    last_90d_return NUMERIC,
    walk_forward_pass_rate NUMERIC,
    walk_forward_windows INTEGER,
    walk_forward_summary JSONB,
    diagnostics JSONB,
    UNIQUE(category, symbol, interval, strategy)
);

CREATE INDEX IF NOT EXISTS idx_strategy_quality_status
ON strategy_quality(category, interval, quality_status, quality_score DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_quality_symbol
ON strategy_quality(category, symbol, interval, strategy, updated_at DESC);

CREATE TABLE IF NOT EXISTS model_runs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    horizon_bars INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    train_rows INTEGER NOT NULL,
    test_rows INTEGER NOT NULL,
    accuracy NUMERIC,
    precision_score NUMERIC,
    recall_score NUMERIC,
    roc_auc NUMERIC,
    feature_importance JSONB,
    params JSONB
);

CREATE INDEX IF NOT EXISTS idx_model_runs_lookup
ON model_runs(category, interval, symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS paper_trades (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry NUMERIC NOT NULL,
    stop_loss NUMERIC,
    take_profit NUMERIC,
    qty NUMERIC,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed','cancelled','rejected')),
    rationale JSONB
);


CREATE TABLE IF NOT EXISTS llm_evaluations (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT REFERENCES signals(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    category TEXT,
    symbol TEXT NOT NULL,
    interval TEXT,
    strategy TEXT,
    direction TEXT,
    model TEXT,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','ok','error','skipped')),
    brief TEXT,
    error TEXT,
    duration_ms INTEGER,
    payload JSONB,
    UNIQUE(signal_id)
);

CREATE INDEX IF NOT EXISTS idx_llm_evaluations_lookup
ON llm_evaluations(status, updated_at DESC, symbol);

CREATE INDEX IF NOT EXISTS idx_llm_evaluations_symbol_time
ON llm_evaluations(symbol, updated_at DESC);


-- Recommendation contract constraints and outcome lifecycle.
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
-- V29: market-data integrity and stored recommendation TTL.
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
-- V34: explicit recommendation contract version, terminal quality views and stale-write guard.
-- Safe to re-run. Existing legacy rows are not rewritten; new/updated directional
-- recommendations must be current at write time.

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
        IF NEW.expires_at <= NOW() THEN
            RAISE EXCEPTION 'directional recommendation cannot be inserted already expired';
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

CREATE OR REPLACE VIEW v_recommendation_outcome_quality_v34 AS
WITH terminal AS (
    SELECT s.category,
           s.symbol,
           s.interval,
           s.strategy,
           s.direction,
           o.signal_id,
           o.evaluated_at,
           o.outcome_status,
           COALESCE(o.realized_r, 0)::numeric AS realized_r,
           o.max_favorable_excursion_r,
           o.max_adverse_excursion_r
    FROM recommendation_outcomes o
    JOIN signals s ON s.id = o.signal_id
    WHERE o.outcome_status <> 'open'
), curve AS (
    SELECT *,
           SUM(realized_r) OVER (PARTITION BY category, symbol, interval, strategy, direction ORDER BY evaluated_at, signal_id) AS equity_r
    FROM terminal
), dd AS (
    SELECT *,
           equity_r - MAX(equity_r) OVER (PARTITION BY category, symbol, interval, strategy, direction ORDER BY evaluated_at, signal_id) AS drawdown_r
    FROM curve
)
SELECT category,
       symbol,
       interval,
       strategy,
       direction,
       COUNT(*)::int AS evaluated,
       AVG(realized_r)::float AS expectancy_r,
       SUM(realized_r)::float AS cumulative_r,
       MIN(drawdown_r)::float AS max_drawdown_r,
       SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS winrate,
       SUM(GREATEST(realized_r, 0))::float / NULLIF(ABS(SUM(LEAST(realized_r, 0)))::float, 0) AS profit_factor,
       AVG(max_favorable_excursion_r)::float AS avg_mfe_r,
       AVG(max_adverse_excursion_r)::float AS avg_mae_r,
       MAX(evaluated_at) AS last_evaluated_at
FROM dd
GROUP BY category, symbol, interval, strategy, direction;

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_signal_time_v34
ON recommendation_outcomes(signal_id, evaluated_at DESC, outcome_status);
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
-- V36: publish the recommendation contract metadata and protect the UI source of truth.
-- Safe to re-run. This migration does not rewrite existing signals; it adds a
-- metadata view and an index aligned with /api/recommendations/active.

CREATE OR REPLACE VIEW v_recommendation_contract_v36 AS
SELECT
    'recommendation_v36'::text AS contract_version,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/history'::text AS history_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'confidence_score is an engineering setup score, not an exact win probability'::text AS confidence_semantics,
    jsonb_build_object(
        'directions', jsonb_build_array('long','short','no_trade'),
        'statuses', jsonb_build_array('review_entry','research_candidate','wait','blocked','expired','invalid','missed_entry'),
        'price_statuses', jsonb_build_array('entry_zone','extended','moved_away','stale','unknown','no_setup'),
        'required_fields', jsonb_build_array(
            'symbol','trade_direction','entry','stop_loss','take_profit',
            'risk_pct','expected_reward_pct','risk_reward','confidence_score',
            'expires_at','recommendation_explanation','signal_breakdown','price_actionability'
        )
    ) AS contract_schema;

CREATE INDEX IF NOT EXISTS idx_signals_active_source_v36
ON signals(category, symbol, interval, expires_at DESC, created_at DESC)
WHERE direction IN ('long','short')
  AND bar_time IS NOT NULL
  AND expires_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_recommendation_operator_actions_signal_time_v36
ON recommendation_operator_actions(signal_id, created_at DESC, action);
-- V37: outbound contract guardrails, net-R/R awareness and DB integrity audit.
-- Safe to re-run. New constraints are NOT VALID so legacy rows can be audited
-- through v_recommendation_integrity_audit_v37 before optional validation.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_rationale_json_object_v37') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_rationale_json_object_v37 CHECK (
            rationale IS NULL OR jsonb_typeof(rationale) = 'object'
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_operator_actions_payload_object_v37') THEN
        ALTER TABLE recommendation_operator_actions ADD CONSTRAINT ck_recommendation_operator_actions_payload_object_v37 CHECK (
            payload IS NOT NULL AND jsonb_typeof(payload) = 'object'
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_outcomes_notes_object_v37') THEN
        ALTER TABLE recommendation_outcomes ADD CONSTRAINT ck_recommendation_outcomes_notes_object_v37 CHECK (
            notes IS NULL OR jsonb_typeof(notes) = 'object'
        ) NOT VALID;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_signal_recommendation_contract_v37()
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
        IF NEW.expires_at <= NOW() THEN
            RAISE EXCEPTION 'directional recommendation cannot be inserted already expired';
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
        IF NEW.rationale IS NOT NULL AND jsonb_typeof(NEW.rationale) <> 'object' THEN
            RAISE EXCEPTION 'directional recommendation rationale must be a JSON object';
        END IF;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_enforce_signal_recommendation_contract_v31 ON signals;
CREATE TRIGGER trg_enforce_signal_recommendation_contract_v31
BEFORE INSERT OR UPDATE ON signals
FOR EACH ROW
EXECUTE FUNCTION enforce_signal_recommendation_contract_v37();

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v37 AS
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_expires_at'::text AS issue_code, 'error'::text AS severity,
       'Directional recommendation has no expires_at.'::text AS detail,
       s.created_at
FROM signals s
WHERE s.direction IN ('long','short') AND s.expires_at IS NULL
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'expired_directional_signal', 'error',
       'Directional recommendation is already expired and must not be active.', s.created_at
FROM signals s
WHERE s.direction IN ('long','short') AND s.expires_at IS NOT NULL AND s.expires_at <= NOW()
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'invalid_long_levels', 'error',
       'LONG requires stop_loss < entry < take_profit.', s.created_at
FROM signals s
WHERE s.direction = 'long' AND NOT (s.stop_loss < s.entry AND s.entry < s.take_profit)
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'invalid_short_levels', 'error',
       'SHORT requires take_profit < entry < stop_loss.', s.created_at
FROM signals s
WHERE s.direction = 'short' AND NOT (s.take_profit < s.entry AND s.entry < s.stop_loss)
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'invalid_confidence', 'error',
       'Directional confidence must be in [0,1].', s.created_at
FROM signals s
WHERE s.direction IN ('long','short') AND (s.confidence IS NULL OR s.confidence < 0 OR s.confidence > 1)
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_terminal_outcome_fields', 'error',
       'Terminal outcome is missing exit/realized-R fields required for quality statistics.', s.created_at
FROM signals s
JOIN recommendation_outcomes o ON o.signal_id = s.id
WHERE o.outcome_status IN ('hit_take_profit','hit_stop_loss','closed_manual')
  AND (o.exit_time IS NULL OR o.exit_price IS NULL OR o.realized_r IS NULL)
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'rationale_not_object', 'warn',
       'Rationale should be a JSON object so raw indicators, votes and explanations stay parseable.', s.created_at
FROM signals s
WHERE s.rationale IS NOT NULL AND jsonb_typeof(s.rationale) <> 'object';

CREATE OR REPLACE VIEW v_recommendation_contract_v37 AS
SELECT
    'recommendation_v37'::text AS contract_version,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/history'::text AS history_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    '/api/system/warnings'::text AS integrity_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'confidence_score is an engineering setup score, not an exact win probability'::text AS confidence_semantics,
    'entry_zone_only_for_actionable_review'::text AS price_gate_policy,
    jsonb_build_object(
        'directions', jsonb_build_array('long','short','no_trade'),
        'statuses', jsonb_build_array('review_entry','research_candidate','wait','blocked','expired','invalid','missed_entry'),
        'price_statuses', jsonb_build_array('entry_zone','extended','moved_away','stale','unknown','no_setup'),
        'required_fields', jsonb_build_array(
            'symbol','trade_direction','entry','stop_loss','take_profit',
            'risk_pct','expected_reward_pct','risk_reward','net_risk_reward','confidence_score',
            'expires_at','recommendation_explanation','signal_breakdown','price_actionability','contract_health'
        )
    ) AS contract_schema;

CREATE INDEX IF NOT EXISTS idx_signals_integrity_audit_v37
ON signals(category, direction, expires_at, created_at DESC)
WHERE direction IN ('long','short');

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_quality_segments_v37
ON recommendation_outcomes(signal_id, outcome_status, evaluated_at DESC, realized_r)
WHERE outcome_status <> 'open';
