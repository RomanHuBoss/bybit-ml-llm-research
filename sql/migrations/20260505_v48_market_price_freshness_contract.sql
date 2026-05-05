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
