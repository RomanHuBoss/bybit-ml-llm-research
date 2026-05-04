-- V40: keep operator-queue consolidation and outbound recommendation contract consistent.
-- Safe to re-run. The runtime fix is in Python; this migration publishes the
-- corresponding DB audit/version contract and keeps active LONG/SHORT conflicts
-- visible to /api/system/warnings.

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v40 AS
SELECT * FROM v_recommendation_integrity_audit_v38
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'operator_contract_conflict_mismatch'::text AS issue_code,
       'error'::text AS severity,
       'Active LONG/SHORT conflict exists for the same market/bar. Runtime must consolidate before contract enrichment so nested recommendation is NO_TRADE, not stale REVIEW_ENTRY.'::text AS detail,
       s.created_at
FROM signals s
JOIN (
    SELECT category, symbol, interval, bar_time
    FROM signals
    WHERE direction IN ('long','short')
      AND bar_time IS NOT NULL
      AND expires_at IS NOT NULL
      AND expires_at > NOW()
    GROUP BY category, symbol, interval, bar_time
    HAVING COUNT(DISTINCT direction) > 1
) c ON c.category=s.category AND c.symbol=s.symbol AND c.interval=s.interval AND c.bar_time=s.bar_time
WHERE s.direction IN ('long','short')
  AND s.expires_at > NOW();

CREATE OR REPLACE VIEW v_recommendation_contract_v40 AS
SELECT
    'recommendation_v40'::text AS contract_version,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/history'::text AS history_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    '/api/system/warnings'::text AS integrity_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'server_enriched_contract_v40'::text AS decision_source,
    false AS frontend_may_recalculate,
    'confidence_score is an engineering setup score, not an exact win probability'::text AS confidence_semantics,
    'operator_queue_consolidates_before_contract_enrichment'::text AS operator_queue_policy,
    'entry_zone_only_for_actionable_review'::text AS price_gate_policy,
    jsonb_build_object(
        'directions', jsonb_build_array('long','short','no_trade'),
        'statuses', jsonb_build_array('review_entry','research_candidate','wait','blocked','expired','invalid','missed_entry'),
        'price_statuses', jsonb_build_array('entry_zone','extended','moved_away','stale','unknown','no_setup'),
        'required_fields', jsonb_build_array(
            'symbol','trade_direction','entry','stop_loss','take_profit',
            'risk_pct','expected_reward_pct','risk_reward','net_risk_reward','confidence_score',
            'expires_at','checked_at','ttl_status','ttl_seconds_left',
            'recommendation_explanation','signal_breakdown','price_actionability','contract_health',
            'decision_source','frontend_may_recalculate'
        ),
        'forbidden_frontend_behaviors', jsonb_build_array(
            'recompute_trade_direction','recompute_risk_reward','upgrade_no_trade_to_entry','ignore_price_actionability'
        )
    ) AS contract_schema;

CREATE INDEX IF NOT EXISTS idx_signals_active_contract_v40
ON signals(category, symbol, interval, bar_time DESC, expires_at DESC, created_at DESC)
WHERE direction IN ('long','short')
  AND bar_time IS NOT NULL
  AND expires_at IS NOT NULL;
