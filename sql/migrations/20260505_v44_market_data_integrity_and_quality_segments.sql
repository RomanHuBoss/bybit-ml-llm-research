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
