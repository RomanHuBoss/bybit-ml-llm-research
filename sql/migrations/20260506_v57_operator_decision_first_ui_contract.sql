-- V57: audit-контракт для decision-first frontend.
-- Проверка не меняет торговую логику, а выявляет active directional-рекомендации,
-- которые нельзя понятно показать оператору без догадок на фронте.
CREATE OR REPLACE VIEW v_operator_decision_first_ui_contract_v57 AS
WITH active_directional AS (
    SELECT s.id, s.category, s.symbol, s.interval, s.strategy, s.direction,
           s.confidence, s.entry, s.stop_loss, s.take_profit, s.risk_reward,
           s.expires_at, s.rationale, s.created_at
    FROM signals s
    WHERE s.direction IN ('long', 'short')
      AND s.bar_time IS NOT NULL
      AND s.expires_at IS NOT NULL
      AND s.expires_at > NOW()
      AND NOT EXISTS (
          SELECT 1
          FROM recommendation_outcomes o
          WHERE o.signal_id = s.id
            AND o.outcome_status <> 'open'
      )
)
SELECT id, category, symbol, interval, strategy, direction,
       'operator_explanation_missing_v57'::text AS issue_code,
       'warn'::text AS severity,
       'Directional recommendation has no human-readable explanation for the operator cockpit.'::text AS detail,
       created_at
FROM active_directional
WHERE rationale IS NULL OR jsonb_typeof(rationale) <> 'object'
   OR COALESCE(NULLIF(rationale->>'recommendation_explanation', ''), NULLIF(rationale->>'operator_explanation', ''), NULLIF(rationale->>'explanation', '')) IS NULL
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'operator_next_action_missing_v57'::text AS issue_code,
       'warn'::text AS severity,
       'Directional recommendation has no server-owned next action/actionability payload.'::text AS detail,
       created_at
FROM active_directional
WHERE rationale IS NULL OR jsonb_typeof(rationale) <> 'object'
   OR NOT (rationale ? 'next_actions' OR rationale ? 'primary_next_action' OR rationale ? 'price_actionability')
UNION ALL
SELECT id, category, symbol, interval, strategy, direction,
       'operator_signal_breakdown_missing_v57'::text AS issue_code,
       'warn'::text AS severity,
       'Directional recommendation has no signal_breakdown for the decision details dialog.'::text AS detail,
       created_at
FROM active_directional
WHERE rationale IS NULL OR jsonb_typeof(rationale) <> 'object'
   OR NOT (rationale ? 'signal_breakdown' OR rationale ? 'votes' OR rationale ? 'why');
