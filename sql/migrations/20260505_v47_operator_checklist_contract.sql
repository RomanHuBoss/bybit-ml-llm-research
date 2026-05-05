-- V47: publish server-owned operator checklist and nested recommendation identity.
-- Runtime now sends category/symbol/interval/strategy and operator_checklist inside
-- the nested recommendation object so frontend does not recompute critical trade gates.

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
