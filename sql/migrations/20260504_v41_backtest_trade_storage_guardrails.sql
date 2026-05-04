-- V41 Backtest trade storage guardrails
-- Safe to run more than once.
-- Fix scope: сохраняет корректную структуру сделок бэктеста и добавляет DB-защиту
-- от невозможных направлений, нулевых цен и обратного порядка времени.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_backtest_trades_quality_lookup_v41
ON backtest_trades(symbol, strategy, direction, exit_time DESC);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_backtest_trades_direction_v41') THEN
        ALTER TABLE backtest_trades
        ADD CONSTRAINT chk_backtest_trades_direction_v41
        CHECK (direction IN ('long','short')) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_backtest_trades_prices_v41') THEN
        ALTER TABLE backtest_trades
        ADD CONSTRAINT chk_backtest_trades_prices_v41
        CHECK (entry > 0 AND exit > 0) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_backtest_trades_time_order_v41') THEN
        ALTER TABLE backtest_trades
        ADD CONSTRAINT chk_backtest_trades_time_order_v41
        CHECK (exit_time >= entry_time) NOT VALID;
    END IF;
END $$;

COMMIT;
