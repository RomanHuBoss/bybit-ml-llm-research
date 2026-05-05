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
           CASE WHEN s.entry IS NOT NULL AND s.entry > 0 AND s.stop_loss IS NOT NULL THEN ABS(s.entry::numeric - s.stop_loss::numeric) / s.entry::numeric END AS risk_pct
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
       jsonb_build_object('atr_pct', atr_pct, 'risk_pct', risk_pct)::text,
       created_at
FROM active_directional
WHERE atr_pct > 0.18 OR risk_pct > 0.15
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'unexplained_directional_payload_v53', 'warn',
       jsonb_build_object('rationale_type', jsonb_typeof(rationale), 'rationale', rationale)::text,
       created_at
FROM active_directional
WHERE rationale IS NULL OR jsonb_typeof(rationale) <> 'object'
   OR NOT (rationale ? 'votes' OR rationale ? 'signal_breakdown' OR rationale ? 'explanation' OR rationale ? 'why');
