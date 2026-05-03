-- V34: explicit recommendation contract version, terminal quality views and stale-write guard.
-- Safe to re-run. Existing legacy rows are not rewritten; new/updated directional
-- recommendations must be current at write time.

CREATE OR REPLACE FUNCTION enforce_signal_recommendation_contract_v31()
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
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_enforce_signal_recommendation_contract_v31 ON signals;
CREATE TRIGGER trg_enforce_signal_recommendation_contract_v31
BEFORE INSERT OR UPDATE ON signals
FOR EACH ROW
EXECUTE FUNCTION enforce_signal_recommendation_contract_v31();

CREATE OR REPLACE VIEW v_recommendation_outcome_quality_v34 AS
WITH terminal AS (
    SELECT s.category,
           s.symbol,
           s.interval,
           s.strategy,
           s.direction,
           o.signal_id,
           o.evaluated_at,
           o.outcome_status,
           COALESCE(o.realized_r, 0)::numeric AS realized_r,
           o.max_favorable_excursion_r,
           o.max_adverse_excursion_r
    FROM recommendation_outcomes o
    JOIN signals s ON s.id = o.signal_id
    WHERE o.outcome_status <> 'open'
), curve AS (
    SELECT *,
           SUM(realized_r) OVER (PARTITION BY category, symbol, interval, strategy, direction ORDER BY evaluated_at, signal_id) AS equity_r
    FROM terminal
), dd AS (
    SELECT *,
           equity_r - MAX(equity_r) OVER (PARTITION BY category, symbol, interval, strategy, direction ORDER BY evaluated_at, signal_id) AS drawdown_r
    FROM curve
)
SELECT category,
       symbol,
       interval,
       strategy,
       direction,
       COUNT(*)::int AS evaluated,
       AVG(realized_r)::float AS expectancy_r,
       SUM(realized_r)::float AS cumulative_r,
       MIN(drawdown_r)::float AS max_drawdown_r,
       SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS winrate,
       SUM(GREATEST(realized_r, 0))::float / NULLIF(ABS(SUM(LEAST(realized_r, 0)))::float, 0) AS profit_factor,
       AVG(max_favorable_excursion_r)::float AS avg_mfe_r,
       AVG(max_adverse_excursion_r)::float AS avg_mae_r,
       MAX(evaluated_at) AS last_evaluated_at
FROM dd
GROUP BY category, symbol, interval, strategy, direction;

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_signal_time_v34
ON recommendation_outcomes(signal_id, evaluated_at DESC, outcome_status);
