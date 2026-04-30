-- V20 Strategy Lab database migration
-- Safe to run more than once.
-- Applies the DB objects required by Strategy Lab, strategy_quality extended evidence,
-- and persisted backtest trades used for expectancy / walk-forward diagnostics.

BEGIN;

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

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_exit
ON backtest_trades(run_id, exit_time);

CREATE TABLE IF NOT EXISTS strategy_quality (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    strategy TEXT NOT NULL,
    quality_status TEXT NOT NULL DEFAULT 'RESEARCH',
    quality_score NUMERIC NOT NULL DEFAULT 0,
    evidence_grade TEXT NOT NULL DEFAULT 'INSUFFICIENT',
    quality_reason TEXT,
    backtest_run_id BIGINT,
    last_backtest_at TIMESTAMPTZ,
    total_return NUMERIC,
    max_drawdown NUMERIC,
    sharpe NUMERIC,
    win_rate NUMERIC,
    profit_factor NUMERIC,
    trades_count INTEGER NOT NULL DEFAULT 0,
    diagnostics JSONB
);

ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS symbol TEXT;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS interval TEXT;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS strategy TEXT;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS quality_status TEXT DEFAULT 'RESEARCH';
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS quality_score NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS evidence_grade TEXT NOT NULL DEFAULT 'INSUFFICIENT';
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS quality_reason TEXT;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS backtest_run_id BIGINT;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS last_backtest_at TIMESTAMPTZ;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS total_return NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS max_drawdown NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS sharpe NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS win_rate NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS profit_factor NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS trades_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS expectancy NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS avg_trade_pnl NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS median_trade_pnl NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS last_30d_return NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS last_90d_return NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS walk_forward_pass_rate NUMERIC;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS walk_forward_windows INTEGER;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS walk_forward_summary JSONB;
ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS diagnostics JSONB;

UPDATE strategy_quality
SET quality_status = 'RESEARCH'
WHERE quality_status IS NULL
   OR quality_status NOT IN ('APPROVED','WATCHLIST','RESEARCH','REJECTED','STALE');

ALTER TABLE strategy_quality ALTER COLUMN quality_status SET DEFAULT 'RESEARCH';
ALTER TABLE strategy_quality ALTER COLUMN quality_status SET NOT NULL;
ALTER TABLE strategy_quality ALTER COLUMN evidence_grade SET DEFAULT 'INSUFFICIENT';
ALTER TABLE strategy_quality ALTER COLUMN quality_score SET DEFAULT 0;
ALTER TABLE strategy_quality ALTER COLUMN trades_count SET DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_strategy_quality_status'
    ) THEN
        ALTER TABLE strategy_quality
        ADD CONSTRAINT ck_strategy_quality_status
        CHECK (quality_status IN ('APPROVED','WATCHLIST','RESEARCH','REJECTED','STALE'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_strategy_quality_backtest_run'
    ) THEN
        ALTER TABLE strategy_quality
        ADD CONSTRAINT fk_strategy_quality_backtest_run
        FOREIGN KEY (backtest_run_id) REFERENCES backtest_runs(id) ON DELETE SET NULL;
    END IF;
END $$;

WITH ranked AS (
    SELECT ctid,
           ROW_NUMBER() OVER (
               PARTITION BY category, symbol, interval, strategy
               ORDER BY updated_at DESC NULLS LAST, id DESC
           ) AS rn
    FROM strategy_quality
    WHERE category IS NOT NULL
      AND symbol IS NOT NULL
      AND interval IS NOT NULL
      AND strategy IS NOT NULL
)
DELETE FROM strategy_quality sq
USING ranked r
WHERE sq.ctid = r.ctid
  AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS ux_strategy_quality_key
ON strategy_quality(category, symbol, interval, strategy);

CREATE INDEX IF NOT EXISTS idx_strategy_quality_status
ON strategy_quality(category, interval, quality_status, quality_score DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_quality_symbol
ON strategy_quality(category, symbol, interval, strategy, updated_at DESC);

COMMIT;
