-- V43: recent realised-outcome quarantine for advisory recommendations.
-- Safe to re-run. The runtime gate is in app/recommendation.py; this view makes
-- the same failure mode visible to /api/system/warnings and DB operators.

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_recent_v43
ON recommendation_outcomes(signal_id, evaluated_at DESC, id DESC)
WHERE outcome_status <> 'open';

CREATE OR REPLACE VIEW v_recommendation_recent_outcome_quality_v43 AS
WITH ranked AS (
    SELECT s.category, s.symbol, s.interval, s.strategy, s.direction,
           o.outcome_status, o.realized_r, o.evaluated_at,
           ROW_NUMBER() OVER (
               PARTITION BY s.category, s.symbol, s.interval, s.strategy, s.direction
               ORDER BY o.evaluated_at DESC, o.id DESC
           ) AS rn
    FROM recommendation_outcomes o
    JOIN signals s ON s.id = o.signal_id
    WHERE o.outcome_status <> 'open'
      AND s.direction IN ('long','short')
), recent AS (
    SELECT * FROM ranked WHERE rn <= 20
)
SELECT category, symbol, interval, strategy, direction,
       COUNT(*)::int AS recent_outcomes_count,
       COUNT(*) FILTER (WHERE COALESCE(realized_r, 0) < 0)::int AS recent_loss_count,
       (COUNT(*) FILTER (WHERE COALESCE(realized_r, 0) < 0)::float / NULLIF(COUNT(*)::float, 0)) AS recent_loss_rate,
       AVG(realized_r)::float AS recent_average_r,
       (SUM(GREATEST(COALESCE(realized_r, 0), 0))::float / NULLIF(ABS(SUM(LEAST(COALESCE(realized_r, 0), 0)))::float, 0)) AS recent_profit_factor,
       CASE
           WHEN MIN(CASE WHEN COALESCE(realized_r, 0) >= 0 THEN rn END) IS NULL THEN COUNT(*)::int
           ELSE GREATEST(MIN(CASE WHEN COALESCE(realized_r, 0) >= 0 THEN rn END) - 1, 0)::int
       END AS recent_consecutive_losses,
       MAX(evaluated_at) AS recent_last_evaluated_at
FROM recent
GROUP BY category, symbol, interval, strategy, direction;

CREATE OR REPLACE VIEW v_recommendation_integrity_audit_v43 AS
SELECT * FROM v_recommendation_integrity_audit_v40
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'recent_loss_quarantine'::text AS issue_code,
       'error'::text AS severity,
       ('Recent completed recommendations are losing: loss_rate=' || ROUND(q.recent_loss_rate::numeric, 4)::text || ', avg_r=' || ROUND(COALESCE(q.recent_average_r, 0)::numeric, 4)::text)::text AS detail,
       s.created_at
FROM signals s
JOIN v_recommendation_recent_outcome_quality_v43 q
  ON q.category=s.category AND q.symbol=s.symbol AND q.interval=s.interval AND q.strategy=s.strategy AND q.direction=s.direction
WHERE s.direction IN ('long','short')
  AND s.expires_at IS NOT NULL
  AND s.expires_at > NOW()
  AND q.recent_outcomes_count >= 5
  AND q.recent_loss_rate >= 0.75
  AND COALESCE(q.recent_average_r, 0) <= -0.10
UNION ALL
SELECT s.id AS signal_id, s.category, s.symbol, s.interval, s.strategy, s.direction,
       'loss_streak_quarantine'::text AS issue_code,
       'error'::text AS severity,
       ('Recent consecutive losses=' || q.recent_consecutive_losses::text || '; new REVIEW_ENTRY must be blocked until strategy is reassessed.')::text AS detail,
       s.created_at
FROM signals s
JOIN v_recommendation_recent_outcome_quality_v43 q
  ON q.category=s.category AND q.symbol=s.symbol AND q.interval=s.interval AND q.strategy=s.strategy AND q.direction=s.direction
WHERE s.direction IN ('long','short')
  AND s.expires_at IS NOT NULL
  AND s.expires_at > NOW()
  AND q.recent_consecutive_losses >= 3;
