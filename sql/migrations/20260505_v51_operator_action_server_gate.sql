-- V51: server-side gate for paper operator actions.
-- Frontend button disable is UX only; the database and API must also reject unsafe
-- paper-entry audit rows for non-actionable or non-REVIEW_ENTRY contracts.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_operator_actions_paper_price_v51') THEN
        ALTER TABLE recommendation_operator_actions ADD CONSTRAINT ck_recommendation_operator_actions_paper_price_v51 CHECK (
            action <> 'paper_opened' OR observed_price > 0
        ) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_recommendation_operator_actions_paper_status_v51') THEN
        ALTER TABLE recommendation_operator_actions ADD CONSTRAINT ck_recommendation_operator_actions_paper_status_v51 CHECK (
            action <> 'paper_opened'
            OR (
                recommendation_status = 'review_entry'
                AND payload ? 'is_actionable'
                AND payload ? 'contract_health_ok'
                AND COALESCE((payload->>'is_actionable')::boolean, false) = true
                AND COALESCE((payload->>'contract_health_ok')::boolean, false) = true
                AND payload->>'price_status' = 'entry_zone'
            )
        ) NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_recommendation_operator_actions_paper_audit_v51
ON recommendation_operator_actions(action, created_at DESC, recommendation_status)
WHERE action = 'paper_opened';

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v51 AS
SELECT * FROM v_recommendation_integrity_audit_v48
UNION ALL
SELECT a.signal_id,
       s.category,
       s.symbol,
       s.interval,
       s.strategy,
       s.direction,
       'operator_paper_opened_without_positive_price'::text AS issue_code,
       'error'::text AS severity,
       a.created_at AS detected_at,
       jsonb_build_object('action_id', a.id, 'observed_price', a.observed_price) AS details
FROM recommendation_operator_actions a
JOIN signals s ON s.id = a.signal_id
WHERE a.action = 'paper_opened'
  AND (a.observed_price IS NULL OR a.observed_price <= 0)
UNION ALL
SELECT a.signal_id,
       s.category,
       s.symbol,
       s.interval,
       s.strategy,
       s.direction,
       'operator_paper_opened_without_server_gate'::text AS issue_code,
       'error'::text AS severity,
       a.created_at AS detected_at,
       jsonb_build_object(
           'action_id', a.id,
           'recommendation_status', a.recommendation_status,
           'price_status', a.payload->>'price_status',
           'is_actionable', a.payload->>'is_actionable',
           'contract_health_ok', a.payload->>'contract_health_ok'
       ) AS details
FROM recommendation_operator_actions a
JOIN signals s ON s.id = a.signal_id
WHERE a.action = 'paper_opened'
  AND (
       a.recommendation_status IS DISTINCT FROM 'review_entry'
       OR a.payload->>'price_status' IS DISTINCT FROM 'entry_zone'
       OR COALESCE((a.payload->>'is_actionable')::boolean, false) IS DISTINCT FROM true
       OR COALESCE((a.payload->>'contract_health_ok')::boolean, false) IS DISTINCT FROM true
  );
