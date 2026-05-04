-- V38: make the recommendation contract strictly server-owned.
-- Frontend may render entry/SL/TP/R/R/confidence, but must not recompute trade math
-- or upgrade a degraded raw signal into a trade recommendation.
-- Safe to re-run. New checks are NOT VALID where legacy rows may need audit first.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_directional_ttl_upper_bound_v38') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_directional_ttl_upper_bound_v38 CHECK (
            direction NOT IN ('long','short')
            OR expires_at IS NULL
            OR bar_time IS NULL
            OR expires_at <= bar_time + INTERVAL '32 days'
        ) NOT VALID;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_signal_recommendation_contract_v38()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    ttl_limit interval := INTERVAL '32 days';
BEGIN
    IF NEW.direction IN ('long','short') THEN
        IF NEW.category IS NULL OR btrim(NEW.category) = '' THEN
            RAISE EXCEPTION 'directional recommendation requires category';
        END IF;
        IF NEW.symbol IS NULL OR btrim(NEW.symbol) = '' THEN
            RAISE EXCEPTION 'directional recommendation requires symbol';
        END IF;
        IF NEW.interval IS NULL OR NEW.interval NOT IN ('1','3','5','15','30','60','120','240','360','720','D','W','M') THEN
            RAISE EXCEPTION 'directional recommendation has incompatible timeframe: %', NEW.interval;
        END IF;
        IF NEW.bar_time IS NULL THEN
            RAISE EXCEPTION 'directional recommendation requires bar_time';
        END IF;
        IF NEW.expires_at IS NULL OR NEW.expires_at <= NEW.bar_time THEN
            RAISE EXCEPTION 'directional recommendation requires expires_at after bar_time';
        END IF;
        IF NEW.expires_at <= NOW() THEN
            RAISE EXCEPTION 'directional recommendation cannot be inserted already expired';
        END IF;
        IF NEW.expires_at > NEW.bar_time + ttl_limit THEN
            RAISE EXCEPTION 'directional recommendation ttl is too long: expires_at %, bar_time %', NEW.expires_at, NEW.bar_time;
        END IF;
        IF NEW.confidence IS NULL OR NEW.confidence < 0 OR NEW.confidence > 1 THEN
            RAISE EXCEPTION 'directional recommendation confidence must be in [0,1]';
        END IF;
        IF NEW.entry IS NULL OR NEW.stop_loss IS NULL OR NEW.take_profit IS NULL OR NEW.atr IS NULL THEN
            RAISE EXCEPTION 'directional recommendation requires entry, stop_loss, take_profit and atr';
        END IF;
        IF NEW.entry <= 0 OR NEW.stop_loss <= 0 OR NEW.take_profit <= 0 OR NEW.atr <= 0 THEN
            RAISE EXCEPTION 'directional recommendation levels and atr must be positive';
        END IF;
        IF NEW.direction = 'long' AND NOT (NEW.stop_loss < NEW.entry AND NEW.entry < NEW.take_profit) THEN
            RAISE EXCEPTION 'invalid LONG levels: require stop_loss < entry < take_profit';
        END IF;
        IF NEW.direction = 'short' AND NOT (NEW.take_profit < NEW.entry AND NEW.entry < NEW.stop_loss) THEN
            RAISE EXCEPTION 'invalid SHORT levels: require take_profit < entry < stop_loss';
        END IF;
        IF NEW.rationale IS NOT NULL AND jsonb_typeof(NEW.rationale) <> 'object' THEN
            RAISE EXCEPTION 'directional recommendation rationale must be a JSON object';
        END IF;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_enforce_signal_recommendation_contract_v31 ON signals;
CREATE TRIGGER trg_enforce_signal_recommendation_contract_v31
BEFORE INSERT OR UPDATE ON signals
FOR EACH ROW
EXECUTE FUNCTION enforce_signal_recommendation_contract_v38();

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v38 AS
SELECT * FROM v_recommendation_integrity_audit_v37
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'ttl_too_long'::text AS issue_code, 'error'::text AS severity,
       'Directional recommendation expires too far after its market bar.'::text AS detail,
       s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND s.bar_time IS NOT NULL
  AND s.expires_at IS NOT NULL
  AND s.expires_at > s.bar_time + INTERVAL '32 days'
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'low_risk_reward_active', 'warn',
       'Directional signal has positive but weak R/R; it must remain WAIT/NO_TRADE unless backend quality gates explicitly allow review.', s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND s.risk_reward IS NOT NULL
  AND s.risk_reward > 0
  AND s.risk_reward < 1.15
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_explanation_payload', 'warn',
       'Directional recommendation lacks reason/votes/signal_breakdown in rationale; UI explanation will be degraded.', s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND (s.rationale IS NULL OR jsonb_typeof(s.rationale) <> 'object'
       OR NOT (s.rationale ? 'reason' OR s.rationale ? 'votes' OR s.rationale ? 'signal_breakdown'))
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_timeframe_context', 'warn',
       'Directional recommendation does not expose timeframes_used/timeframes; operator cannot verify MTF context from UI alone.', s.created_at
FROM signals s
WHERE s.direction IN ('long','short')
  AND (s.rationale IS NULL OR jsonb_typeof(s.rationale) <> 'object'
       OR NOT (s.rationale ? 'timeframes_used' OR s.rationale ? 'timeframes'))
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'active_direction_conflict', 'error',
       'Same market/bar has both active LONG and SHORT directional signals; operator queue must publish NO_TRADE until conflict is resolved.', s.created_at
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

CREATE OR REPLACE VIEW v_recommendation_contract_v38 AS
SELECT
    'recommendation_v38'::text AS contract_version,
    '/api/recommendations/active'::text AS active_endpoint,
    '/api/recommendations/history'::text AS history_endpoint,
    '/api/recommendations/quality'::text AS quality_endpoint,
    '/api/system/warnings'::text AS integrity_endpoint,
    'recommendations_active'::text AS frontend_source_of_truth,
    'server_enriched_contract_v38'::text AS decision_source,
    false AS frontend_may_recalculate,
    'confidence_score is an engineering setup score, not an exact win probability'::text AS confidence_semantics,
    'entry_zone_only_for_actionable_review'::text AS price_gate_policy,
    jsonb_build_object(
        'directions', jsonb_build_array('long','short','no_trade'),
        'statuses', jsonb_build_array('review_entry','research_candidate','wait','blocked','expired','invalid','missed_entry'),
        'price_statuses', jsonb_build_array('entry_zone','extended','moved_away','stale','unknown','no_setup'),
        'required_fields', jsonb_build_array(
            'symbol','trade_direction','entry','stop_loss','take_profit',
            'risk_pct','expected_reward_pct','risk_reward','net_risk_reward','confidence_score',
            'expires_at','recommendation_explanation','signal_breakdown','price_actionability','contract_health',
            'decision_source','frontend_may_recalculate'
        )
    ) AS contract_schema;

CREATE INDEX IF NOT EXISTS idx_signals_active_contract_v38
ON signals(category, symbol, interval, bar_time DESC, expires_at DESC, created_at DESC)
WHERE direction IN ('long','short')
  AND bar_time IS NOT NULL
  AND expires_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_signals_active_direction_conflict_v38
ON signals(category, symbol, interval, bar_time, direction, expires_at DESC)
WHERE direction IN ('long','short')
  AND bar_time IS NOT NULL
  AND expires_at IS NOT NULL;
