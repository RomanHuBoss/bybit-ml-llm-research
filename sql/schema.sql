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
