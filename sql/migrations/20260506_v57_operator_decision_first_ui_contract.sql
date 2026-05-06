-- V57: audit-контракт для decision-first frontend.
-- Проверка не меняет торговую логику, а выявляет active directional-рекомендации,
-- которые нельзя понятно показать оператору без догадок на фронте.
CREATE OR REPLACE VIEW v_operator_decision_first_ui_contract_v57 AS
WITH active_directional AS (
    SELECT id, category, symbol, interval, strategy, direction, signal_score, confidence, entry, stop_loss, take_profit, risk_reward, expires_at, rationale, created_at
    FROM signals
    WHERE active IS TRUE AND direction IN ('long', 'short')
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
