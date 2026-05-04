-- V36: publish the recommendation contract metadata and protect the UI source of truth.
-- Safe to re-run. This migration does not rewrite existing signals; it adds a
-- metadata view and an index aligned with /api/recommendations/active.

CREATE OR REPLACE VIEW v_recommendation_contract_v36 AS
SELECT
    'recommendation_v36'::text AS contract_version,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/history'::text AS history_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'confidence_score is an engineering setup score, not an exact win probability'::text AS confidence_semantics,
    jsonb_build_object(
        'directions', jsonb_build_array('long','short','no_trade'),
        'statuses', jsonb_build_array('review_entry','research_candidate','wait','blocked','expired','invalid','missed_entry'),
        'price_statuses', jsonb_build_array('entry_zone','extended','moved_away','stale','unknown','no_setup'),
        'required_fields', jsonb_build_array(
            'symbol','trade_direction','entry','stop_loss','take_profit',
            'risk_pct','expected_reward_pct','risk_reward','confidence_score',
            'expires_at','recommendation_explanation','signal_breakdown','price_actionability'
        )
    ) AS contract_schema;

CREATE INDEX IF NOT EXISTS idx_signals_active_source_v36
ON signals(category, symbol, interval, expires_at DESC, created_at DESC)
WHERE direction IN ('long','short')
  AND bar_time IS NOT NULL
  AND expires_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_recommendation_operator_actions_signal_time_v36
ON recommendation_operator_actions(signal_id, created_at DESC, action);
