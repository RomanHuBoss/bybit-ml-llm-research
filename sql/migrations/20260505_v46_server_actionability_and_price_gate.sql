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
