-- V37: outbound contract guardrails, net-R/R awareness and DB integrity audit.
-- Safe to re-run. New constraints are NOT VALID so legacy rows can be audited
-- through v_recommendation_integrity_audit_v37 before optional validation.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_signals_rationale_json_object_v37') THEN
        ALTER TABLE signals ADD CONSTRAINT ck_signals_rationale_json_object_v37 CHECK (
            rationale IS NULL OR jsonb_typeof(rationale) = 'object'
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_operator_actions_payload_object_v37') THEN
        ALTER TABLE recommendation_operator_actions ADD CONSTRAINT ck_recommendation_operator_actions_payload_object_v37 CHECK (
            payload IS NOT NULL AND jsonb_typeof(payload) = 'object'
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_outcomes_notes_object_v37') THEN
        ALTER TABLE recommendation_outcomes ADD CONSTRAINT ck_recommendation_outcomes_notes_object_v37 CHECK (
            notes IS NULL OR jsonb_typeof(notes) = 'object'
        ) NOT VALID;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_signal_recommendation_contract_v37()
RETURNS trigger
LANGUAGE plpgsql
AS $$
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
EXECUTE FUNCTION enforce_signal_recommendation_contract_v37();

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v37 AS
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_expires_at'::text AS issue_code, 'error'::text AS severity,
       'Directional recommendation has no expires_at.'::text AS detail,
       s.created_at
FROM signals s
WHERE s.direction IN ('long','short') AND s.expires_at IS NULL
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'expired_directional_signal', 'error',
       'Directional recommendation is already expired and must not be active.', s.created_at
FROM signals s
WHERE s.direction IN ('long','short') AND s.expires_at IS NOT NULL AND s.expires_at <= NOW()
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'invalid_long_levels', 'error',
       'LONG requires stop_loss < entry < take_profit.', s.created_at
FROM signals s
WHERE s.direction = 'long' AND NOT (s.stop_loss < s.entry AND s.entry < s.take_profit)
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'invalid_short_levels', 'error',
       'SHORT requires take_profit < entry < stop_loss.', s.created_at
FROM signals s
WHERE s.direction = 'short' AND NOT (s.take_profit < s.entry AND s.entry < s.stop_loss)
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'invalid_confidence', 'error',
       'Directional confidence must be in [0,1].', s.created_at
FROM signals s
WHERE s.direction IN ('long','short') AND (s.confidence IS NULL OR s.confidence < 0 OR s.confidence > 1)
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'missing_terminal_outcome_fields', 'error',
       'Terminal outcome is missing exit/realized-R fields required for quality statistics.', s.created_at
FROM signals s
JOIN recommendation_outcomes o ON o.signal_id = s.id
WHERE o.outcome_status IN ('hit_take_profit','hit_stop_loss','closed_manual')
  AND (o.exit_time IS NULL OR o.exit_price IS NULL OR o.realized_r IS NULL)
UNION ALL
SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'rationale_not_object', 'warn',
       'Rationale should be a JSON object so raw indicators, votes and explanations stay parseable.', s.created_at
FROM signals s
WHERE s.rationale IS NOT NULL AND jsonb_typeof(s.rationale) <> 'object';

CREATE OR REPLACE VIEW v_recommendation_contract_v37 AS
SELECT
    'recommendation_v37'::text AS contract_version,
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
        'price_statuses', jsonb_build_array('entry_zone','extended','moved_away','stale','unknown','no_setup'),
        'required_fields', jsonb_build_array(
            'symbol','trade_direction','entry','stop_loss','take_profit',
            'risk_pct','expected_reward_pct','risk_reward','net_risk_reward','confidence_score',
            'expires_at','recommendation_explanation','signal_breakdown','price_actionability','contract_health'
        )
    ) AS contract_schema;

CREATE INDEX IF NOT EXISTS idx_signals_integrity_audit_v37
ON signals(category, direction, expires_at, created_at DESC)
WHERE direction IN ('long','short');

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_quality_segments_v37
ON recommendation_outcomes(signal_id, outcome_status, evaluated_at DESC, realized_r)
WHERE outcome_status <> 'open';
