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
