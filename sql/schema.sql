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
    direction TEXT NOT NULL CHECK (direction IN ('long','short')),
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ NOT NULL CHECK (exit_time >= entry_time),
    entry NUMERIC NOT NULL CHECK (entry > 0),
    exit NUMERIC NOT NULL CHECK (exit > 0),
    pnl NUMERIC NOT NULL,
    pnl_pct NUMERIC NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
ON backtest_trades(run_id);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_exit
ON backtest_trades(run_id, exit_time);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_quality_lookup_v41
ON backtest_trades(symbol, strategy, direction, exit_time DESC);


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
-- V38: make the recommendation contract strictly server-owned.
-- Frontend may render entry/SL/TP/R/R/confidence, but must not recompute trade math
-- or upgrade a degraded raw signal into a trade recommendation.
-- Safe to re-run. New checks are NOT VALID where legacy rows may need audit first.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_directional_ttl_upper_bound_v38') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_directional_ttl_upper_bound_v38 CHECK (
            direction NOT IN ('long','short')
            OR expires_at IS NULL
            OR bar_time IS NULL
            OR expires_at <= bar_time + INTERVAL '32 days'
        ) NOT VALID;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_signal_recommendation_contract_v38()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    ttl_limit interval := INTERVAL '32 days';
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
        IF NEW.expires_at > NEW.bar_time + ttl_limit THEN
            RAISE EXCEPTION 'directional recommendation ttl is too long: expires_at %, bar_time %', NEW.expires_at, NEW.bar_time;
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
EXECUTE FUNCTION enforce_signal_recommendation_contract_v38();

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v38 AS
SELECT * FROM v_recommendation_integrity_audit_v37
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'ttl_too_long'::text AS issue_code, 'error'::text AS severity,
       'Directional recommendation expires too far after its market bar.'::text AS detail,
       s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND s.bar_time IS NOT NULL
  AND s.expires_at IS NOT NULL
  AND s.expires_at > s.bar_time + INTERVAL '32 days'
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'low_risk_reward_active', 'warn',
       'Directional signal has positive but weak R/R; it must remain WAIT/NO_TRADE unless backend quality gates explicitly allow review.', s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND s.risk_reward IS NOT NULL
  AND s.risk_reward > 0
  AND s.risk_reward < 1.15
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_explanation_payload', 'warn',
       'Directional recommendation lacks reason/votes/signal_breakdown in rationale; UI explanation will be degraded.', s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND (s.rationale IS NULL OR jsonb_typeof(s.rationale) <> 'object'
       OR NOT (s.rationale ? 'reason' OR s.rationale ? 'votes' OR s.rationale ? 'signal_breakdown'))
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_timeframe_context', 'warn',
       'Directional recommendation does not expose timeframes_used/timeframes; operator cannot verify MTF context from UI alone.', s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND (s.rationale IS NULL OR jsonb_typeof(s.rationale) <> 'object'
       OR NOT (s.rationale ? 'timeframes_used' OR s.rationale ? 'timeframes'))
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'active_direction_conflict', 'error',
       'Same market/bar has both active LONG and SHORT directional signals; operator queue must publish NO_TRADE until conflict is resolved.', s.created_at
FROM signals s
JOIN (
    SELECT category, symbol, interval, bar_time
    FROM signals
    WHERE direction IN ('long','short')
      AND bar_time IS NOT NULL
      AND expires_at IS NOT NULL
      AND expires_at > NOW()
    GROUP BY category, symbol, interval, bar_time
    HAVING COUNT(DISTINCT direction) > 1
) c ON c.category=s.category AND c.symbol=s.symbol AND c.interval=s.interval AND c.bar_time=s.bar_time
WHERE s.direction IN ('long','short')
  AND s.expires_at > NOW();

CREATE OR REPLACE VIEW v_recommendation_contract_v38 AS
SELECT
    'recommendation_v38'::text AS contract_version,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/history'::text AS history_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    '/api/system/warnings'::text AS integrity_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'server_enriched_contract_v38'::text AS decision_source,
    false AS frontend_may_recalculate,
    'confidence_score is an engineering setup score, not an exact win probability'::text AS confidence_semantics,
    'entry_zone_only_for_actionable_review'::text AS price_gate_policy,
    jsonb_build_object(
        'directions', jsonb_build_array('long','short','no_trade'),
        'statuses', jsonb_build_array('review_entry','research_candidate','wait','blocked','expired','invalid','missed_entry'),
        'price_statuses', jsonb_build_array('entry_zone','extended','moved_away','stale','unknown','no_setup'),
        'required_fields', jsonb_build_array(
            'symbol','trade_direction','entry','stop_loss','take_profit',
            'risk_pct','expected_reward_pct','risk_reward','net_risk_reward','confidence_score',
            'expires_at','recommendation_explanation','signal_breakdown','price_actionability','contract_health',
            'decision_source','frontend_may_recalculate'
        )
    ) AS contract_schema;

CREATE INDEX IF NOT EXISTS idx_signals_active_contract_v38
ON signals(category, symbol, interval, bar_time DESC, expires_at DESC, created_at DESC)
WHERE direction IN ('long','short')
  AND bar_time IS NOT NULL
  AND expires_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_signals_active_direction_conflict_v38
ON signals(category, symbol, interval, bar_time, direction, expires_at DESC)
WHERE direction IN ('long','short')
  AND bar_time IS NOT NULL
  AND expires_at IS NOT NULL;
-- V40: keep operator-queue consolidation and outbound recommendation contract consistent.
-- Safe to re-run. The runtime fix is in Python; this migration publishes the
-- corresponding DB audit/version contract and keeps active LONG/SHORT conflicts
-- visible to /api/system/warnings.

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v40 AS
SELECT * FROM v_recommendation_integrity_audit_v38
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'operator_contract_conflict_mismatch'::text AS issue_code,
       'error'::text AS severity,
       'Active LONG/SHORT conflict exists for the same market/bar. Runtime must consolidate before contract enrichment so nested recommendation is NO_TRADE, not stale REVIEW_ENTRY.'::text AS detail,
       s.created_at
FROM signals s
JOIN (
    SELECT category, symbol, interval, bar_time
    FROM signals
    WHERE direction IN ('long','short')
      AND bar_time IS NOT NULL
      AND expires_at IS NOT NULL
      AND expires_at > NOW()
    GROUP BY category, symbol, interval, bar_time
    HAVING COUNT(DISTINCT direction) > 1
) c ON c.category=s.category AND c.symbol=s.symbol AND c.interval=s.interval AND c.bar_time=s.bar_time
WHERE s.direction IN ('long','short')
  AND s.expires_at > NOW();

CREATE OR REPLACE VIEW v_recommendation_contract_v40 AS
SELECT
    'recommendation_v40'::text AS contract_version,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/history'::text AS history_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    '/api/system/warnings'::text AS integrity_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'server_enriched_contract_v40'::text AS decision_source,
    false AS frontend_may_recalculate,
    'confidence_score is an engineering setup score, not an exact win probability'::text AS confidence_semantics,
    'operator_queue_consolidates_before_contract_enrichment'::text AS operator_queue_policy,
    'entry_zone_only_for_actionable_review'::text AS price_gate_policy,
    jsonb_build_object(
        'directions', jsonb_build_array('long','short','no_trade'),
        'statuses', jsonb_build_array('review_entry','research_candidate','wait','blocked','expired','invalid','missed_entry'),
        'price_statuses', jsonb_build_array('entry_zone','extended','moved_away','stale','unknown','no_setup'),
        'required_fields', jsonb_build_array(
            'symbol','trade_direction','entry','stop_loss','take_profit',
            'risk_pct','expected_reward_pct','risk_reward','net_risk_reward','confidence_score',
            'expires_at','checked_at','ttl_status','ttl_seconds_left',
            'recommendation_explanation','signal_breakdown','price_actionability','contract_health',
            'decision_source','frontend_may_recalculate'
        ),
        'forbidden_frontend_behaviors', jsonb_build_array(
            'recompute_trade_direction','recompute_risk_reward','upgrade_no_trade_to_entry','ignore_price_actionability'
        )
    ) AS contract_schema;

CREATE INDEX IF NOT EXISTS idx_signals_active_contract_v40
ON signals(category, symbol, interval, bar_time DESC, expires_at DESC, created_at DESC)
WHERE direction IN ('long','short')
  AND bar_time IS NOT NULL
  AND expires_at IS NOT NULL;

-- V42: explicit conservative same-bar SL/TP execution analytics.
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
-- V43: recent realised-outcome quarantine for advisory recommendations.
-- Safe to re-run. The runtime gate is in app/recommendation.py; this view makes
-- the same failure mode visible to /api/system/warnings and DB operators.

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_recent_v43
ON recommendation_outcomes(signal_id, evaluated_at DESC, id DESC)
WHERE outcome_status <> 'open';

CREATE OR REPLACE VIEW v_recommendation_recent_outcome_quality_v43 AS
WITH ranked AS (
    SELECT s.category, s.symbol, s.interval, s.strategy, s.direction,
           o.outcome_status, o.realized_r, o.evaluated_at,
           ROW_NUMBER() OVER (
               PARTITION BY s.category, s.symbol, s.interval, s.strategy, s.direction
               ORDER BY o.evaluated_at DESC, o.id DESC
           ) AS rn
    FROM recommendation_outcomes o
    JOIN signals s ON s.id = o.signal_id
    WHERE o.outcome_status <> 'open'
      AND s.direction IN ('long','short')
), recent AS (
    SELECT * FROM ranked WHERE rn <= 20
)
SELECT category, symbol, interval, strategy, direction,
       COUNT(*)::int AS recent_outcomes_count,
       COUNT(*) FILTER (WHERE COALESCE(realized_r, 0) < 0)::int AS recent_loss_count,
       (COUNT(*) FILTER (WHERE COALESCE(realized_r, 0) < 0)::float / NULLIF(COUNT(*)::float, 0)) AS recent_loss_rate,
       AVG(realized_r)::float AS recent_average_r,
       (SUM(GREATEST(COALESCE(realized_r, 0), 0))::float / NULLIF(ABS(SUM(LEAST(COALESCE(realized_r, 0), 0)))::float, 0)) AS recent_profit_factor,
       CASE
           WHEN MIN(CASE WHEN COALESCE(realized_r, 0) >= 0 THEN rn END) IS NULL THEN COUNT(*)::int
           ELSE GREATEST(MIN(CASE WHEN COALESCE(realized_r, 0) >= 0 THEN rn END) - 1, 0)::int
       END AS recent_consecutive_losses,
       MAX(evaluated_at) AS recent_last_evaluated_at
FROM recent
GROUP BY category, symbol, interval, strategy, direction;

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v43 AS
SELECT * FROM v_recommendation_integrity_audit_v40
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'recent_loss_quarantine'::text AS issue_code,
       'error'::text AS severity,
       ('Recent completed recommendations are losing: loss_rate=' || ROUND(q.recent_loss_rate::numeric, 4)::text || ', avg_r=' || ROUND(COALESCE(q.recent_average_r, 0)::numeric, 4)::text)::text AS detail,
       s.created_at
FROM signals s
JOIN v_recommendation_recent_outcome_quality_v43 q
  ON q.category=s.category AND q.symbol=s.symbol AND q.interval=s.interval AND q.strategy=s.strategy AND q.direction=s.direction
WHERE s.direction IN ('long','short')
  AND s.expires_at IS NOT NULL
  AND s.expires_at > NOW()
  AND q.recent_outcomes_count >= 5
  AND q.recent_loss_rate >= 0.75
  AND COALESCE(q.recent_average_r, 0) <= -0.10
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'loss_streak_quarantine'::text AS issue_code,
       'error'::text AS severity,
       ('Recent consecutive losses=' || q.recent_consecutive_losses::text || '; new REVIEW_ENTRY must be blocked until strategy is reassessed.')::text AS detail,
       s.created_at
FROM signals s
JOIN v_recommendation_recent_outcome_quality_v43 q
  ON q.category=s.category AND q.symbol=s.symbol AND q.interval=s.interval AND q.strategy=s.strategy AND q.direction=s.direction
WHERE s.direction IN ('long','short')
  AND s.expires_at IS NOT NULL
  AND s.expires_at > NOW()
  AND q.recent_consecutive_losses >= 3;
-- V44: market-data integrity guardrails and richer recommendation-quality segments.
-- Safe to re-run. New CHECK constraints are NOT VALID so legacy rows can be
-- audited before validation; runtime code now also skips invalid OHLC candles
-- instead of allowing them to distort recommendation outcomes.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_candles_ohlc_integrity_v44') THEN
        ALTER TABLE candles ADD CONSTRAINT ck_candles_ohlc_integrity_v44 CHECK (
            open > 0 AND high > 0 AND low > 0 AND close > 0
            AND volume >= 0
            AND (turnover IS NULL OR turnover >= 0)
            AND high >= low
            AND high >= GREATEST(open, close)
            AND low <= LEAST(open, close)
            AND open::text <> 'NaN' AND high::text <> 'NaN' AND low::text <> 'NaN' AND close::text <> 'NaN'
            AND volume::text <> 'NaN' AND (turnover IS NULL OR turnover::text <> 'NaN')
        ) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_liquidity_snapshot_prices_v44') THEN
        ALTER TABLE liquidity_snapshots ADD CONSTRAINT ck_liquidity_snapshot_prices_v44 CHECK (
            (bid1_price IS NULL OR bid1_price > 0)
            AND (ask1_price IS NULL OR ask1_price > 0)
            AND (last_price IS NULL OR last_price > 0)
            AND (spread_pct IS NULL OR spread_pct >= 0)
            AND (turnover_24h IS NULL OR turnover_24h >= 0)
            AND (volume_24h IS NULL OR volume_24h >= 0)
            AND (open_interest_value IS NULL OR open_interest_value >= 0)
            AND (funding_rate IS NULL OR funding_rate::text <> 'NaN')
            AND (liquidity_score >= 0 AND liquidity_score::text <> 'NaN')
        ) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_outcomes_metrics_v44') THEN
        ALTER TABLE recommendation_outcomes ADD CONSTRAINT ck_recommendation_outcomes_metrics_v44 CHECK (
            (realized_r IS NULL OR realized_r::text <> 'NaN')
            AND (max_favorable_excursion_r IS NULL OR max_favorable_excursion_r::text <> 'NaN')
            AND (max_adverse_excursion_r IS NULL OR max_adverse_excursion_r::text <> 'NaN')
            AND bars_observed >= 0
            AND (notes IS NULL OR jsonb_typeof(notes) = 'object')
        ) NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_candles_integrity_scan_v44
ON candles(category, symbol, interval, start_time DESC)
WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 OR volume < 0 OR high < low;

CREATE INDEX IF NOT EXISTS idx_liquidity_integrity_scan_v44
ON liquidity_snapshots(category, captured_at DESC, symbol)
WHERE spread_pct < 0 OR bid1_price <= 0 OR ask1_price <= 0 OR last_price <= 0;

CREATE OR REPLACE VIEW v_recommendation_quality_segments_v44 AS
WITH completed AS (
    SELECT s.category, s.symbol, s.interval, s.strategy, s.direction,
           COALESCE(NULLIF(s.rationale->>'signal_type',''), NULLIF(s.rationale->>'setup_type',''), s.strategy) AS signal_type,
           CASE
             WHEN s.confidence < 0.55 THEN '<55%'
             WHEN s.confidence < 0.65 THEN '55-65%'
             WHEN s.confidence < 0.75 THEN '65-75%'
             ELSE '>=75%'
           END AS confidence_bucket,
           o.outcome_status, o.realized_r, o.max_favorable_excursion_r, o.max_adverse_excursion_r,
           o.evaluated_at, o.notes
    FROM recommendation_outcomes o
    JOIN signals s ON s.id=o.signal_id
    WHERE o.outcome_status <> 'open'
)
SELECT category, 'symbol'::text AS segment_axis, symbol AS segment_key, COUNT(*)::int AS evaluated,
       AVG(realized_r)::float AS average_r,
       SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) AS winrate,
       SUM(GREATEST(realized_r,0))::float / NULLIF(ABS(SUM(LEAST(realized_r,0)))::float,0) AS profit_factor,
       AVG(max_favorable_excursion_r)::float AS avg_mfe_r,
       AVG(max_adverse_excursion_r)::float AS avg_mae_r
FROM completed
GROUP BY category, symbol
UNION ALL
SELECT category, 'timeframe', interval, COUNT(*)::int,
       AVG(realized_r)::float,
       SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0),
       SUM(GREATEST(realized_r,0))::float / NULLIF(ABS(SUM(LEAST(realized_r,0)))::float,0),
       AVG(max_favorable_excursion_r)::float,
       AVG(max_adverse_excursion_r)::float
FROM completed
GROUP BY category, interval
UNION ALL
SELECT category, 'direction', direction, COUNT(*)::int,
       AVG(realized_r)::float,
       SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0),
       SUM(GREATEST(realized_r,0))::float / NULLIF(ABS(SUM(LEAST(realized_r,0)))::float,0),
       AVG(max_favorable_excursion_r)::float,
       AVG(max_adverse_excursion_r)::float
FROM completed
GROUP BY category, direction
UNION ALL
SELECT category, 'confidence_bucket', confidence_bucket, COUNT(*)::int,
       AVG(realized_r)::float,
       SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0),
       SUM(GREATEST(realized_r,0))::float / NULLIF(ABS(SUM(LEAST(realized_r,0)))::float,0),
       AVG(max_favorable_excursion_r)::float,
       AVG(max_adverse_excursion_r)::float
FROM completed
GROUP BY category, confidence_bucket
UNION ALL
SELECT category, 'signal_type', signal_type, COUNT(*)::int,
       AVG(realized_r)::float,
       SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0),
       SUM(GREATEST(realized_r,0))::float / NULLIF(ABS(SUM(LEAST(realized_r,0)))::float,0),
       AVG(max_favorable_excursion_r)::float,
       AVG(max_adverse_excursion_r)::float
FROM completed
GROUP BY category, signal_type;

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v44 AS
SELECT * FROM v_recommendation_integrity_audit_v43
UNION ALL
SELECT NULL::bigint AS signal_id, c.category, c.symbol, c.interval, 'market_data'::text AS strategy, 'flat'::text AS direction,
       'invalid_ohlc_candle'::text AS issue_code, 'error'::text AS severity,
       ('Invalid OHLC candle at ' || c.start_time::text || ': high/low/open/close/volume are inconsistent.')::text AS detail,
       c.created_at
FROM candles c
WHERE c.open <= 0 OR c.high <= 0 OR c.low <= 0 OR c.close <= 0 OR c.volume < 0
   OR c.high < c.low OR c.high < GREATEST(c.open, c.close) OR c.low > LEAST(c.open, c.close)
UNION ALL
SELECT NULL::bigint AS signal_id, l.category, l.symbol, NULL::text AS interval, 'liquidity'::text AS strategy, 'flat'::text AS direction,
       'invalid_liquidity_snapshot'::text AS issue_code, 'error'::text AS severity,
       ('Invalid liquidity snapshot at ' || l.captured_at::text || ': price/spread/liquidity fields are inconsistent.')::text AS detail,
       l.captured_at AS created_at
FROM liquidity_snapshots l
WHERE l.spread_pct < 0 OR l.bid1_price <= 0 OR l.ask1_price <= 0 OR l.last_price <= 0 OR l.liquidity_score < 0;

CREATE OR REPLACE VIEW v_recommendation_contract_v44 AS
SELECT
    'recommendation_v44'::text AS contract_version,
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
        'quality_segments', jsonb_build_array('symbol','timeframe','direction','confidence_bucket','signal_type'),
        'required_fields', jsonb_build_array(
            'symbol','trade_direction','entry','stop_loss','take_profit',
            'risk_pct','expected_reward_pct','risk_reward','net_risk_reward','confidence_score',
            'expires_at','recommendation_explanation','signal_breakdown','price_actionability','contract_health'
        )
    ) AS contract_schema;
-- V45: nested trade-level contract and signal payload integrity.
-- Runtime now puts entry/SL/TP inside the nested `recommendation` object, not only
-- in the legacy top-level signal row. The DB migration adds repeatable audit hooks
-- for the same invariant without breaking existing data.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_rationale_object_v45') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_rationale_object_v45 CHECK (
            rationale IS NULL OR jsonb_typeof(rationale) = 'object'
        ) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_directional_rationale_shape_v45') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_directional_rationale_shape_v45 CHECK (
            direction = 'flat'
            OR rationale IS NULL
            OR jsonb_typeof(rationale) = 'object'
        ) NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_signals_missing_payload_audit_v45
ON signals(category, symbol, interval, strategy, created_at DESC)
WHERE direction IN ('long','short') AND (rationale IS NULL OR jsonb_typeof(rationale) <> 'object');

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v45 AS
SELECT * FROM v_recommendation_integrity_audit_v44
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_structured_rationale'::text AS issue_code, 'warn'::text AS severity,
       'Directional signal has no structured rationale object; UI explanation will fall back to generic text.'::text AS detail,
       s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND (s.rationale IS NULL OR jsonb_typeof(s.rationale) <> 'object')
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_timeframe_context'::text AS issue_code, 'warn'::text AS severity,
       'Directional signal rationale does not declare timeframes_used/timeframes; MTF audit may be harder for the operator.'::text AS detail,
       s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND jsonb_typeof(s.rationale) = 'object'
  AND NOT (s.rationale ? 'timeframes_used' OR s.rationale ? 'timeframes');

CREATE OR REPLACE VIEW v_recommendation_contract_v45 AS
SELECT
    'recommendation_v40'::text AS public_contract_version,
    'nested_trade_levels_v45'::text AS compatible_extension,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/{signal_id}'::text AS detail_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    '/api/system/warnings'::text AS integrity_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'server_enriched_contract_v40'::text AS decision_source,
    jsonb_build_object(
        'nested_recommendation_required_fields', jsonb_build_array(
            'entry','stop_loss','take_profit','risk_pct','expected_reward_pct','risk_reward',
            'net_risk_reward','confidence_score','expires_at','price_actionability','contract_health'
        ),
        'frontend_may_recalculate', false,
        'directional_level_rules', jsonb_build_object(
            'long', 'stop_loss < entry < take_profit',
            'short', 'take_profit < entry < stop_loss'
        ),
        'compatible_extensions', jsonb_build_array('market_data_integrity_v44','quality_segments_v44','nested_trade_levels_v45')
    ) AS contract_schema;
-- V46: server-side actionability cannot expose REVIEW_ENTRY outside entry-zone.
-- Runtime demotes extended/moved_away price states to missed_entry/NO_TRADE.
-- This migration publishes the matching integrity view so DB/API/UI drift is visible.

CREATE INDEX IF NOT EXISTS idx_signals_active_price_gate_v46
ON signals(category, symbol, interval, bar_time DESC, expires_at DESC, created_at DESC)
WHERE direction IN ('long','short')
  AND bar_time IS NOT NULL
  AND expires_at IS NOT NULL;

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v46 AS
WITH latest_price AS (
    SELECT DISTINCT ON (category, symbol, interval)
           category, symbol, interval, close AS last_price, start_time AS last_price_time
    FROM candles
    ORDER BY category, symbol, interval, start_time DESC
), active_directional AS (
    SELECT s.*, lp.last_price, lp.last_price_time,
           GREATEST(
               0.0015::numeric,
               LEAST(0.018::numeric, (COALESCE(s.atr, 0)::numeric / NULLIF(s.entry, 0)::numeric) * 0.35::numeric)
           ) AS entry_zone_pct,
           ABS(lp.last_price::numeric - s.entry::numeric) / NULLIF(s.entry, 0)::numeric AS price_drift_pct
    FROM signals s
    LEFT JOIN latest_price lp
      ON lp.category=s.category AND lp.symbol=s.symbol AND lp.interval=s.interval
    WHERE s.direction IN ('long','short')
      AND s.entry > 0
      AND s.bar_time IS NOT NULL
      AND s.expires_at IS NOT NULL
      AND s.expires_at > NOW()
)
SELECT * FROM v_recommendation_integrity_audit_v45
UNION ALL
SELECT a.id AS signal_id, a.category, a.symbol, a.interval, a.strategy, a.direction,
       'active_price_outside_entry_zone'::text AS issue_code,
       'warn'::text AS severity,
       ('Latest price drift ' || ROUND((a.price_drift_pct * 100.0)::numeric, 4)::text ||
        '% is outside server entry-zone ' || ROUND((a.entry_zone_pct * 100.0)::numeric, 4)::text ||
        '%. Runtime must demote REVIEW_ENTRY to missed_entry/NO_TRADE until retest or recalculation.')::text AS detail,
       a.created_at
FROM active_directional a
WHERE a.last_price IS NOT NULL
  AND a.price_drift_pct IS NOT NULL
  AND a.price_drift_pct > a.entry_zone_pct;

CREATE OR REPLACE VIEW v_recommendation_contract_v46 AS
SELECT
    'recommendation_v40'::text AS public_contract_version,
    'server_actionability_v46'::text AS compatible_extension,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/{signal_id}'::text AS detail_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    '/api/system/warnings'::text AS integrity_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'server_enriched_contract_v40'::text AS decision_source,
    jsonb_build_object(
        'frontend_may_recalculate', false,
        'review_entry_requires', jsonb_build_array('valid_levels','non_expired','price_status=entry_zone','net_risk_reward>1'),
        'demotion_rule', 'extended_or_moved_away price_status becomes missed_entry/no_trade, never actionable review_entry',
        'compatible_extensions', jsonb_build_array('market_data_integrity_v44','quality_segments_v44','nested_trade_levels_v45','server_actionability_v46')
    ) AS contract_schema;
-- V47: server-owned operator checklist and nested recommendation identity.
CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v47 AS
SELECT * FROM v_recommendation_integrity_audit_v46
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_rationale_risk_payload_v47'::text AS issue_code,
       'warn'::text AS severity,
       'Directional signal rationale lacks server risk payload fields; runtime can enrich from columns, but stored audit trail is incomplete.'::text AS detail,
       s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND jsonb_typeof(s.rationale) = 'object'
  AND NOT (
      s.rationale ? 'risk_pct'
      AND s.rationale ? 'expected_reward_pct'
      AND s.rationale ? 'risk_reward'
      AND s.rationale ? 'invalidation_condition'
      AND s.rationale ? 'expires_at'
  )
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'active_signal_missing_identity_v47'::text AS issue_code,
       'error'::text AS severity,
       'Active directional signal cannot be rendered as a complete nested recommendation because category/symbol/interval/strategy identity is incomplete.'::text AS detail,
       s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND s.expires_at IS NOT NULL
  AND s.expires_at > NOW()
  AND (
      s.category IS NULL OR btrim(s.category) = ''
      OR s.symbol IS NULL OR btrim(s.symbol) = ''
      OR s.interval IS NULL OR btrim(s.interval) = ''
      OR s.strategy IS NULL OR btrim(s.strategy) = ''
  );

CREATE OR REPLACE VIEW v_recommendation_contract_v47 AS
SELECT
    'recommendation_v40'::text AS public_contract_version,
    'operator_checklist_v47'::text AS compatible_extension,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/{signal_id}'::text AS detail_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    '/api/system/warnings'::text AS integrity_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'server_enriched_contract_v40'::text AS decision_source,
    jsonb_build_object(
        'frontend_may_recalculate', false,
        'nested_identity_required', jsonb_build_array('category','symbol','interval','strategy','created_at','bar_time'),
        'operator_checklist_required', true,
        'operator_checklist_item_shape', jsonb_build_object('key','string','status','pass|warn|fail','title','string','text','string'),
        'review_entry_requires', jsonb_build_array('valid_levels','non_expired','price_status=entry_zone','net_risk_reward>1','operator_checklist.price_gate=pass'),
        'compatible_extensions', jsonb_build_array('market_data_integrity_v44','quality_segments_v44','nested_trade_levels_v45','server_actionability_v46','operator_checklist_v47')
    ) AS contract_schema;

-- V48: reference-price freshness guard for advisory recommendations.
-- TTL of a trading idea is not enough: REVIEW_ENTRY must also prove that the
-- current/last price used for the server price gate has a timestamp within a
-- bounded interval budget. Repeatable and backward-compatible.

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v48 AS
WITH latest_price AS (
    SELECT DISTINCT ON (category, symbol, interval)
           category, symbol, interval, close AS last_price, start_time AS last_price_time
    FROM candles
    ORDER BY category, symbol, interval, start_time DESC
), active_directional AS (
    SELECT s.id,
           s.category,
           s.symbol,
           s.interval,
           s.strategy,
           s.direction,
           s.created_at,
           lp.last_price,
           lp.last_price_time,
           CASE
               WHEN s.interval ~ '^[0-9]+$' THEN GREATEST(10, (s.interval::int * 2) + 5)
               WHEN s.interval = 'D' THEN 2885
               WHEN s.interval = 'W' THEN 20165
               WHEN s.interval = 'M' THEN 89285
               ELSE 125
           END AS max_age_minutes
    FROM signals s
    LEFT JOIN latest_price lp
      ON lp.category=s.category AND lp.symbol=s.symbol AND lp.interval=s.interval
    WHERE s.direction IN ('long','short')
      AND s.expires_at IS NOT NULL
      AND s.expires_at > NOW()
)
SELECT * FROM v_recommendation_integrity_audit_v47
UNION ALL
SELECT a.id AS signal_id, a.category, a.symbol, a.interval, a.strategy, a.direction,
       'active_reference_price_missing_v48'::text AS issue_code,
       'error'::text AS severity,
       'Active directional recommendation has no latest candle/reference price for its category/symbol/interval; runtime must block REVIEW_ENTRY.'::text AS detail,
       a.created_at
FROM active_directional a
WHERE a.last_price IS NULL OR a.last_price_time IS NULL
UNION ALL
SELECT a.id AS signal_id, a.category, a.symbol, a.interval, a.strategy, a.direction,
       'active_reference_price_stale_v48'::text AS issue_code,
       'error'::text AS severity,
       ('Latest reference price timestamp ' || a.last_price_time::text ||
        ' is older than freshness budget ' || a.max_age_minutes::text ||
        ' minutes for interval ' || COALESCE(a.interval, 'unknown') ||
        '; runtime must expose price_status=stale and block REVIEW_ENTRY.')::text AS detail,
       a.created_at
FROM active_directional a
WHERE a.last_price_time IS NOT NULL
  AND a.last_price_time < NOW() - (a.max_age_minutes::text || ' minutes')::interval
UNION ALL
SELECT a.id AS signal_id, a.category, a.symbol, a.interval, a.strategy, a.direction,
       'active_reference_price_future_time_v48'::text AS issue_code,
       'error'::text AS severity,
       ('Latest reference price timestamp ' || a.last_price_time::text ||
        ' is in the future relative to DB time; runtime must block REVIEW_ENTRY.')::text AS detail,
       a.created_at
FROM active_directional a
WHERE a.last_price_time IS NOT NULL
  AND a.last_price_time > NOW() + interval '2 minutes';

CREATE OR REPLACE VIEW v_recommendation_contract_v48 AS
SELECT
    'recommendation_v40'::text AS public_contract_version,
    'market_price_freshness_v48'::text AS compatible_extension,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/{signal_id}'::text AS detail_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    '/api/system/warnings'::text AS integrity_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'server_enriched_contract_v40'::text AS decision_source,
    jsonb_build_object(
        'frontend_may_recalculate', false,
        'reference_price_required_fields', jsonb_build_array('market_freshness','last_price_time','last_price_age_seconds','last_price_max_age_seconds'),
        'review_entry_requires', jsonb_build_array('valid_levels','non_expired','price_status=entry_zone','market_freshness.status=fresh','net_risk_reward>1','operator_checklist.price_gate=pass'),
        'stale_price_rule', 'old or missing reference price timestamp forces price_status=stale and blocks REVIEW_ENTRY even if expires_at is still active',
        'compatible_extensions', jsonb_build_array('market_data_integrity_v44','quality_segments_v44','nested_trade_levels_v45','server_actionability_v46','operator_checklist_v47','market_price_freshness_v48')
    ) AS contract_schema;

-- V51: server-side gate for paper operator actions.
-- Frontend button disable is UX only; the database and API must also reject unsafe
-- paper-entry audit rows for non-actionable or non-REVIEW_ENTRY contracts.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_operator_actions_paper_price_v51') THEN
        ALTER TABLE recommendation_operator_actions ADD CONSTRAINT ck_recommendation_operator_actions_paper_price_v51 CHECK (
            action <> 'paper_opened' OR observed_price > 0
        ) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_operator_actions_paper_status_v51') THEN
        ALTER TABLE recommendation_operator_actions ADD CONSTRAINT ck_recommendation_operator_actions_paper_status_v51 CHECK (
            action <> 'paper_opened'
            OR (
                recommendation_status = 'review_entry'
                AND payload ? 'is_actionable'
                AND payload ? 'contract_health_ok'
                AND lower(COALESCE(payload->>'is_actionable', 'false')) = 'true'
                AND lower(COALESCE(payload->>'contract_health_ok', 'false')) = 'true'
                AND payload->>'price_status' = 'entry_zone'
            )
        ) NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_recommendation_operator_actions_paper_audit_v51
ON recommendation_operator_actions(action, created_at DESC, recommendation_status)
WHERE action = 'paper_opened';

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v51 AS
SELECT * FROM v_recommendation_integrity_audit_v48
UNION ALL
SELECT a.signal_id,
       s.category,
       s.symbol,
       s.interval,
       s.strategy,
       s.direction,
       'operator_paper_opened_without_positive_price'::text AS issue_code,
       'error'::text AS severity,
       jsonb_build_object('action_id', a.id, 'observed_price', a.observed_price)::text AS detail,
       a.created_at
FROM recommendation_operator_actions a
JOIN signals s ON s.id = a.signal_id
WHERE a.action = 'paper_opened'
  AND (a.observed_price IS NULL OR a.observed_price <= 0)
UNION ALL
SELECT a.signal_id,
       s.category,
       s.symbol,
       s.interval,
       s.strategy,
       s.direction,
       'operator_paper_opened_without_server_gate'::text AS issue_code,
       'error'::text AS severity,
       jsonb_build_object(
           'action_id', a.id,
           'recommendation_status', a.recommendation_status,
           'price_status', a.payload->>'price_status',
           'is_actionable', a.payload->>'is_actionable',
           'contract_health_ok', a.payload->>'contract_health_ok'
       )::text AS detail,
       a.created_at
FROM recommendation_operator_actions a
JOIN signals s ON s.id = a.signal_id
WHERE a.action = 'paper_opened'
  AND (
       a.recommendation_status IS DISTINCT FROM 'review_entry'
       OR a.payload->>'price_status' IS DISTINCT FROM 'entry_zone'
       OR lower(COALESCE(a.payload->>'is_actionable', 'false')) <> 'true'
       OR lower(COALESCE(a.payload->>'contract_health_ok', 'false')) <> 'true'
  );

-- V52: risk disclosure для оператора и целостность legacy paper-trade.
-- `paper_trades` остается audit/paper-таблицей, а не каналом исполнения.
-- Эти ограничения не дают математически невозможным paper-строкам стать
-- вводящим в заблуждение evidence для советующего cockpit.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_paper_trades_direction_v52') THEN
        ALTER TABLE paper_trades ADD CONSTRAINT ck_paper_trades_direction_v52 CHECK (
            direction IN ('long','short','flat')
        ) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_paper_trades_positive_numbers_v52') THEN
        ALTER TABLE paper_trades ADD CONSTRAINT ck_paper_trades_positive_numbers_v52 CHECK (
            entry > 0
            AND entry::text <> 'NaN'
            AND (stop_loss IS NULL OR (stop_loss > 0 AND stop_loss::text <> 'NaN'))
            AND (take_profit IS NULL OR (take_profit > 0 AND take_profit::text <> 'NaN'))
            AND (qty IS NULL OR (qty > 0 AND qty::text <> 'NaN'))
        ) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_paper_trades_level_side_v52') THEN
        ALTER TABLE paper_trades ADD CONSTRAINT ck_paper_trades_level_side_v52 CHECK (
            direction = 'flat'
            OR (
                direction = 'long'
                AND (stop_loss IS NULL OR stop_loss < entry)
                AND (take_profit IS NULL OR take_profit > entry)
            )
            OR (
                direction = 'short'
                AND (stop_loss IS NULL OR stop_loss > entry)
                AND (take_profit IS NULL OR take_profit < entry)
            )
        ) NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_paper_trades_advisory_audit_v52
ON paper_trades(created_at DESC, symbol, strategy, direction);

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v52 AS
SELECT * FROM v_recommendation_integrity_audit_v51
UNION ALL
SELECT NULL::bigint AS signal_id,
       NULL::text AS category,
       p.symbol,
       NULL::text AS interval,
       p.strategy,
       p.direction,
       'paper_trade_invalid_level_order_v52'::text AS issue_code,
       'error'::text AS severity,
       jsonb_build_object(
           'paper_trade_id', p.id,
           'direction', p.direction,
           'entry', p.entry,
           'stop_loss', p.stop_loss,
           'take_profit', p.take_profit,
           'qty', p.qty
       )::text AS detail,
       p.created_at
FROM paper_trades p
WHERE p.direction NOT IN ('long','short','flat')
   OR p.entry IS NULL OR p.entry <= 0 OR p.entry::text = 'NaN'
   OR (p.stop_loss IS NOT NULL AND (p.stop_loss <= 0 OR p.stop_loss::text = 'NaN'))
   OR (p.take_profit IS NOT NULL AND (p.take_profit <= 0 OR p.take_profit::text = 'NaN'))
   OR (p.qty IS NOT NULL AND (p.qty <= 0 OR p.qty::text = 'NaN'))
   OR (p.direction = 'long' AND ((p.stop_loss IS NOT NULL AND p.stop_loss >= p.entry) OR (p.take_profit IS NOT NULL AND p.take_profit <= p.entry)))
   OR (p.direction = 'short' AND ((p.stop_loss IS NOT NULL AND p.stop_loss <= p.entry) OR (p.take_profit IS NOT NULL AND p.take_profit >= p.entry)));
-- V53: market-context guardrails for advisory recommendations.
-- Миграция безопасна для повторного запуска: ограничения добавляются NOT VALID,
-- legacy-строки остаются видимыми через audit-view до отдельной очистки данных.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_no_numeric_infinity_v53') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_no_numeric_infinity_v53 CHECK (
            confidence::text NOT IN ('NaN','Infinity','-Infinity')
            AND (entry IS NULL OR entry::text NOT IN ('NaN','Infinity','-Infinity'))
            AND (stop_loss IS NULL OR stop_loss::text NOT IN ('NaN','Infinity','-Infinity'))
            AND (take_profit IS NULL OR take_profit::text NOT IN ('NaN','Infinity','-Infinity'))
            AND (atr IS NULL OR atr::text NOT IN ('NaN','Infinity','-Infinity'))
            AND (ml_probability IS NULL OR ml_probability::text NOT IN ('NaN','Infinity','-Infinity'))
            AND (sentiment_score IS NULL OR sentiment_score::text NOT IN ('NaN','Infinity','-Infinity'))
        ) NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_signals_market_context_audit_v53
ON signals(category, symbol, interval, expires_at DESC, bar_time DESC)
WHERE direction IN ('long','short');

CREATE OR REPLACE VIEW v_recommendation_market_context_audit_v53 AS
WITH latest_price AS (
    SELECT DISTINCT ON (category, symbol, interval)
           category, symbol, interval, close AS last_price, start_time AS last_price_time
    FROM candles
    ORDER BY category, symbol, interval, start_time DESC
), active_directional AS (
    SELECT s.*, lp.last_price, lp.last_price_time,
           ABS(lp.last_price::numeric - s.entry::numeric) / NULLIF(s.entry, 0)::numeric AS price_drift_pct,
           CASE WHEN s.entry IS NOT NULL AND s.entry > 0 AND s.atr IS NOT NULL THEN s.atr::numeric / s.entry::numeric END AS atr_pct,
           CASE WHEN s.entry IS NOT NULL AND s.entry > 0 AND s.stop_loss IS NOT NULL THEN ABS(s.entry::numeric - s.stop_loss::numeric) / s.entry::numeric END AS calc_risk_pct
    FROM signals s
    LEFT JOIN latest_price lp
      ON lp.category=s.category AND lp.symbol=s.symbol AND lp.interval=s.interval
    WHERE s.direction IN ('long','short')
)
SELECT id AS signal_id, category, symbol, interval, strategy, direction,
       'confidence_out_of_range_v53'::text AS issue_code,
       'error'::text AS severity,
       jsonb_build_object('confidence', confidence)::text AS detail,
       created_at
FROM active_directional
WHERE confidence IS NULL OR confidence < 0 OR confidence > 1 OR confidence::text IN ('NaN','Infinity','-Infinity')
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'numeric_non_finite_v53', 'error',
       jsonb_build_object('entry', entry, 'stop_loss', stop_loss, 'take_profit', take_profit, 'atr', atr, 'ml_probability', ml_probability, 'sentiment_score', sentiment_score)::text,
       created_at
FROM active_directional
WHERE COALESCE(entry::text IN ('NaN','Infinity','-Infinity'), false)
   OR COALESCE(stop_loss::text IN ('NaN','Infinity','-Infinity'), false)
   OR COALESCE(take_profit::text IN ('NaN','Infinity','-Infinity'), false)
   OR COALESCE(atr::text IN ('NaN','Infinity','-Infinity'), false)
   OR COALESCE(ml_probability::text IN ('NaN','Infinity','-Infinity'), false)
   OR COALESCE(sentiment_score::text IN ('NaN','Infinity','-Infinity'), false)
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'missing_market_timestamp_v53', 'error',
       jsonb_build_object('bar_time', bar_time, 'last_price_time', last_price_time)::text,
       created_at
FROM active_directional
WHERE bar_time IS NULL OR last_price_time IS NULL
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'expired_contract_v53', 'error',
       jsonb_build_object('expires_at', expires_at, 'bar_time', bar_time)::text,
       created_at
FROM active_directional
WHERE expires_at IS NULL OR expires_at <= NOW()
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'invalid_directional_levels_v53', 'error',
       jsonb_build_object('entry', entry, 'stop_loss', stop_loss, 'take_profit', take_profit, 'direction', direction)::text,
       created_at
FROM active_directional
WHERE entry IS NULL OR stop_loss IS NULL OR take_profit IS NULL
   OR entry <= 0 OR stop_loss <= 0 OR take_profit <= 0
   OR (direction = 'long' AND NOT (stop_loss < entry AND entry < take_profit))
   OR (direction = 'short' AND NOT (take_profit < entry AND entry < stop_loss))
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'extreme_atr_distance_v53', 'warn',
       jsonb_build_object('atr_pct', atr_pct, 'risk_pct', calc_risk_pct)::text,
       created_at
FROM active_directional
WHERE atr_pct > 0.18 OR calc_risk_pct > 0.15
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'unexplained_directional_payload_v53', 'warn',
       jsonb_build_object('rationale_type', jsonb_typeof(rationale), 'rationale', rationale)::text,
       created_at
FROM active_directional
WHERE rationale IS NULL OR jsonb_typeof(rationale) <> 'object'
   OR NOT (rationale ? 'votes' OR rationale ? 'signal_breakdown' OR rationale ? 'explanation' OR rationale ? 'why');
-- V54: quote freshness audit and deterministic recommendation-level drawdown.
-- Safe to re-run. This does not change trading behavior, but makes stale quote
-- diagnostics visible at DB/API level and fixes equal-timestamp ordering for R-curve drawdown.

CREATE OR REPLACE VIEW v_market_quote_freshness_audit_v54 AS
WITH latest AS (
    SELECT DISTINCT ON (category, symbol, interval)
           category, symbol, interval, start_time AS last_price_time, close AS last_price,
           open, high, low, volume, created_at
    FROM candles
    ORDER BY category, symbol, interval, start_time DESC
), budgets AS (
    SELECT *,
           LEAST(
               172800,
               GREATEST(
                   600,
                   CASE interval
                       WHEN '1' THEN 1 * 60 * 2 + 300
                       WHEN '3' THEN 3 * 60 * 2 + 300
                       WHEN '5' THEN 5 * 60 * 2 + 300
                       WHEN '15' THEN 15 * 60 * 2 + 300
                       WHEN '30' THEN 30 * 60 * 2 + 300
                       WHEN '60' THEN 60 * 60 * 2 + 300
                       WHEN '120' THEN 120 * 60 * 2 + 300
                       WHEN '240' THEN 240 * 60 * 2 + 300
                       WHEN '360' THEN 360 * 60 * 2 + 300
                       WHEN '720' THEN 720 * 60 * 2 + 300
                       WHEN 'D' THEN 86400 * 2 + 300
                       WHEN 'W' THEN 604800 * 2 + 300
                       WHEN 'M' THEN 2678400 * 2 + 300
                       ELSE 3900
                   END
               )
           )::int AS max_age_seconds,
           EXTRACT(EPOCH FROM (NOW() - last_price_time))::int AS age_seconds
    FROM latest
)
SELECT category, symbol, interval,
       'latest_quote_stale_v54'::text AS issue_code,
       'warn'::text AS severity,
       ('Latest quote age ' || age_seconds::text || ' sec exceeds interval-aware budget ' || max_age_seconds::text || ' sec.')::text AS detail,
       created_at
FROM budgets
WHERE age_seconds > max_age_seconds
UNION ALL
SELECT category, symbol, interval,
       'latest_quote_future_time_v54'::text AS issue_code,
       'error'::text AS severity,
       ('Latest quote timestamp is in the future: ' || last_price_time::text)::text AS detail,
       created_at
FROM budgets
WHERE last_price_time > NOW()
UNION ALL
SELECT category, symbol, interval,
       'latest_quote_invalid_price_v54'::text AS issue_code,
       'error'::text AS severity,
       'Latest quote OHLC values are non-positive or NaN.'::text AS detail,
       created_at
FROM budgets
WHERE last_price IS NULL OR last_price <= 0 OR last_price::text IN ('NaN','Infinity','-Infinity')
   OR open <= 0 OR high <= 0 OR low <= 0
   OR open::text IN ('NaN','Infinity','-Infinity')
   OR high::text IN ('NaN','Infinity','-Infinity')
   OR low::text IN ('NaN','Infinity','-Infinity');

CREATE OR REPLACE VIEW v_recommendation_quality_drawdown_v54 AS
WITH ordered AS (
    SELECT s.category, s.interval, o.signal_id, o.evaluated_at,
           COALESCE(o.realized_r, 0)::float AS realized_r,
           SUM(COALESCE(o.realized_r, 0)::float) OVER (
               PARTITION BY s.category, s.interval
               ORDER BY o.evaluated_at, o.signal_id
           ) AS equity_r
    FROM recommendation_outcomes o
    JOIN signals s ON s.id=o.signal_id
    WHERE o.outcome_status <> 'open'
), curve AS (
    SELECT category, interval, signal_id, evaluated_at, realized_r, equity_r,
           MAX(equity_r) OVER (
               PARTITION BY category, interval
               ORDER BY evaluated_at, signal_id
           ) AS peak_r
    FROM ordered
)
SELECT category, interval,
       COUNT(*)::int AS evaluated,
       COALESCE(MIN(equity_r - peak_r), 0)::float AS max_drawdown_r,
       COALESCE(SUM(realized_r), 0)::float AS cumulative_r,
       AVG(realized_r)::float AS expectancy_r
FROM curve
GROUP BY category, interval;

CREATE OR REPLACE VIEW v_recommendation_contract_v54 AS
SELECT
    'recommendation_v40'::text AS contract_version,
    'quote_freshness_and_quality_drawdown_v54'::text AS extension,
    '/api/quotes/latest'::text AS quotes_endpoint,
    'v_market_quote_freshness_audit_v54'::text AS quote_freshness_audit_view,
    'v_recommendation_quality_drawdown_v54'::text AS recommendation_quality_drawdown_view,
    'latest quote freshness uses interval-aware budget: 2 closed bars + 5 minutes, not MAX_SIGNAL_AGE_HOURS'::text AS quote_freshness_policy,
    'drawdown R-curve is ordered by evaluated_at and signal_id to avoid nondeterminism for equal timestamps'::text AS drawdown_policy;


-- V57: audit-контракт для decision-first frontend.
-- Проверка не меняет торговую логику, а выявляет active directional-рекомендации,
-- которые нельзя понятно показать оператору без догадок на фронте.
CREATE OR REPLACE VIEW v_operator_decision_first_ui_contract_v57 AS
WITH active_directional AS (
    SELECT id, category, symbol, interval, strategy, direction, signal_score, confidence, entry, stop_loss, take_profit, risk_reward, expires_at, rationale, created_at
    FROM signals
    WHERE active IS TRUE AND direction IN ('long', 'short')
)
SELECT id, category, symbol, interval, strategy, direction,
       'operator_explanation_missing_v57'::text AS issue_code,
       'warn'::text AS severity,
       'Directional recommendation has no human-readable explanation for the operator cockpit.'::text AS detail,
       created_at
FROM active_directional
WHERE rationale IS NULL OR jsonb_typeof(rationale) <> 'object'
   OR COALESCE(NULLIF(rationale->>'recommendation_explanation', ''), NULLIF(rationale->>'operator_explanation', ''), NULLIF(rationale->>'explanation', '')) IS NULL
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'operator_next_action_missing_v57'::text AS issue_code,
       'warn'::text AS severity,
       'Directional recommendation has no server-owned next action/actionability payload.'::text AS detail,
       created_at
FROM active_directional
WHERE rationale IS NULL OR jsonb_typeof(rationale) <> 'object'
   OR NOT (rationale ? 'next_actions' OR rationale ? 'primary_next_action' OR rationale ? 'price_actionability')
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'operator_signal_breakdown_missing_v57'::text AS issue_code,
       'warn'::text AS severity,
       'Directional recommendation has no signal_breakdown for the decision details dialog.'::text AS detail,
       created_at
FROM active_directional
WHERE rationale IS NULL OR jsonb_typeof(rationale) <> 'object'
   OR NOT (rationale ? 'signal_breakdown' OR rationale ? 'votes' OR rationale ? 'why');
