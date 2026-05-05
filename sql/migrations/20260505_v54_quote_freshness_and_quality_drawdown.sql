-- V54: quote freshness audit and deterministic recommendation-level drawdown.
-- Safe to re-run. This does not change trading behavior, but makes stale quote
-- diagnostics visible at DB/API level and fixes equal-timestamp ordering for R-curve drawdown.

CREATE OR REPLACE VIEW v_market_quote_freshness_audit_v54 AS
WITH latest AS (
    SELECT DISTINCT ON (category, symbol, interval)
           category, symbol, interval, start_time AS last_price_time, close AS last_price,
           open, high, low, volume, created_at
    FROM candles
    ORDER BY category, symbol, interval, start_time DESC
), budgets AS (
    SELECT *,
           LEAST(
               172800,
               GREATEST(
                   600,
                   CASE interval
                       WHEN '1' THEN 1 * 60 * 2 + 300
                       WHEN '3' THEN 3 * 60 * 2 + 300
                       WHEN '5' THEN 5 * 60 * 2 + 300
                       WHEN '15' THEN 15 * 60 * 2 + 300
                       WHEN '30' THEN 30 * 60 * 2 + 300
                       WHEN '60' THEN 60 * 60 * 2 + 300
                       WHEN '120' THEN 120 * 60 * 2 + 300
                       WHEN '240' THEN 240 * 60 * 2 + 300
                       WHEN '360' THEN 360 * 60 * 2 + 300
                       WHEN '720' THEN 720 * 60 * 2 + 300
                       WHEN 'D' THEN 86400 * 2 + 300
                       WHEN 'W' THEN 604800 * 2 + 300
                       WHEN 'M' THEN 2678400 * 2 + 300
                       ELSE 3900
                   END
               )
           )::int AS max_age_seconds,
           EXTRACT(EPOCH FROM (NOW() - last_price_time))::int AS age_seconds
    FROM latest
)
SELECT category, symbol, interval,
       'latest_quote_stale_v54'::text AS issue_code,
       'warn'::text AS severity,
       ('Latest quote age ' || age_seconds::text || ' sec exceeds interval-aware budget ' || max_age_seconds::text || ' sec.')::text AS detail,
       created_at
FROM budgets
WHERE age_seconds > max_age_seconds
UNION ALL
SELECT category, symbol, interval,
       'latest_quote_future_time_v54'::text AS issue_code,
       'error'::text AS severity,
       ('Latest quote timestamp is in the future: ' || last_price_time::text)::text AS detail,
       created_at
FROM budgets
WHERE last_price_time > NOW()
UNION ALL
SELECT category, symbol, interval,
       'latest_quote_invalid_price_v54'::text AS issue_code,
       'error'::text AS severity,
       'Latest quote OHLC values are non-positive or NaN.'::text AS detail,
       created_at
FROM budgets
WHERE last_price IS NULL OR last_price <= 0 OR last_price::text IN ('NaN','Infinity','-Infinity')
   OR open <= 0 OR high <= 0 OR low <= 0
   OR open::text IN ('NaN','Infinity','-Infinity')
   OR high::text IN ('NaN','Infinity','-Infinity')
   OR low::text IN ('NaN','Infinity','-Infinity');

CREATE OR REPLACE VIEW v_recommendation_quality_drawdown_v54 AS
WITH ordered AS (
    SELECT s.category, s.interval, o.signal_id, o.evaluated_at,
           COALESCE(o.realized_r, 0)::float AS realized_r,
           SUM(COALESCE(o.realized_r, 0)::float) OVER (
               PARTITION BY s.category, s.interval
               ORDER BY o.evaluated_at, o.signal_id
           ) AS equity_r
    FROM recommendation_outcomes o
    JOIN signals s ON s.id=o.signal_id
    WHERE o.outcome_status <> 'open'
), curve AS (
    SELECT category, interval, signal_id, evaluated_at, realized_r, equity_r,
           MAX(equity_r) OVER (
               PARTITION BY category, interval
               ORDER BY evaluated_at, signal_id
           ) AS peak_r
    FROM ordered
)
SELECT category, interval,
       COUNT(*)::int AS evaluated,
       COALESCE(MIN(equity_r - peak_r), 0)::float AS max_drawdown_r,
       COALESCE(SUM(realized_r), 0)::float AS cumulative_r,
       AVG(realized_r)::float AS expectancy_r
FROM curve
GROUP BY category, interval;

CREATE OR REPLACE VIEW v_recommendation_contract_v54 AS
SELECT
    'recommendation_v40'::text AS contract_version,
    'quote_freshness_and_quality_drawdown_v54'::text AS extension,
    '/api/quotes/latest'::text AS quotes_endpoint,
    'v_market_quote_freshness_audit_v54'::text AS quote_freshness_audit_view,
    'v_recommendation_quality_drawdown_v54'::text AS recommendation_quality_drawdown_view,
    'latest quote freshness uses interval-aware budget: 2 closed bars + 5 minutes, not MAX_SIGNAL_AGE_HOURS'::text AS quote_freshness_policy,
    'drawdown R-curve is ordered by evaluated_at and signal_id to avoid nondeterminism for equal timestamps'::text AS drawdown_policy;
