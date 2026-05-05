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
