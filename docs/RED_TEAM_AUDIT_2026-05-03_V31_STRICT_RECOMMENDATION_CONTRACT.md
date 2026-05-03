# Red-team audit — V31 strict recommendation contract

Date: 2026-05-03

## Scope

This iteration hardens the end-to-end recommendation contract for the advisory Bybit trading system. The goal is not cosmetic UI cleanup, but a stricter pipeline from PostgreSQL data integrity through FastAPI DTOs and the frontend cockpit.

## Problems found

1. API request models allowed unknown fields, so frontend/backend drift could be silently ignored.
2. Empty active recommendations were represented mostly as an empty list; the UI had to infer whether this meant `NO_TRADE`, stale data, unavailable API, or simply no current setup.
3. `risk_pct`, `expected_reward_pct`, and `risk_reward` were computed in Python but not materialized and protected in PostgreSQL as a first-class contract.
4. The recommendation outcome lifecycle allowed insufficiently explicit terminal/open field semantics.
5. The detail UI showed execution/risk fields, but did not surface a compact operator explanation block for factors, timeframes, statistical confidence, indicator values, and next actions.

## Implemented changes

### Backend / FastAPI

- Added `StrictAPIModel` with `extra="forbid"` and migrated externally supplied request DTOs to it.
- `/api/recommendations/active` now returns `market_state` with explicit status and explanation.
- `/api/recommendations/quality` now returns `quality_assessment` that separates sample size confidence from signal confidence.
- Recommendation summary contract version moved to `recommendation_v31` while preserving a `previous_contract` compatibility marker.

### Recommendation contract

`trade_contract.enrich_recommendation_row()` now includes:

- `statistics_confidence`
- `timeframes_used`
- `indicator_values`
- `trading_signals`
- `next_actions`

This makes the frontend a renderer of the backend decision rather than a secondary trading-logic engine.

### PostgreSQL

Added migration:

`sql/migrations/20260503_v31_strict_recommendation_contract.sql`

It adds:

- generated `signals.risk_pct`
- generated `signals.expected_reward_pct`
- generated `signals.risk_reward`
- `ck_signals_generated_risk_metrics_v31`
- `ck_recommendation_outcome_terminal_fields_v31`
- trigger function `enforce_signal_recommendation_contract_v31()`
- trigger `trg_enforce_signal_recommendation_contract_v31`
- index `idx_signals_active_contract_v31`
- view `v_recommendation_quality_summary`

The trigger blocks directional recommendations without identity, timeframe, timestamp, TTL, confidence, entry/SL/TP/ATR, or correct LONG/SHORT level ordering.

### Frontend

- `refreshSignals()` now calls `/api/recommendations/active` first and falls back to `/api/signals/latest` only for degraded legacy compatibility.
- Empty-state copy now uses backend `market_state.explanation`.
- Recommendation detail now includes cards for:
  - why the signal appeared;
  - factors against the trade;
  - timeframes used;
  - statistical confidence/sample size;
  - indicator values;
  - next actions.

### Tests

Added:

`tests/test_recommendation_contract_v31.py`

Coverage:

- strict Pydantic unknown-field rejection;
- V31 enriched contract fields;
- `market_state` NO_TRADE explanation;
- V31 migration/schema hardening;
- frontend active recommendation endpoint and detail blocks.

## Verification

Executed successfully:

```bash
python -m py_compile $(find app -name '*.py' | sort)
node --check frontend/app.js
python -m pytest -q tests
```

Result:

```text
179 passed
```

## Remaining work

- Run V31 migration against the real PostgreSQL instance and audit legacy rows that fail the new constraints.
- Add a visual history page for similar signals and confidence buckets.
- Add CI integration against an ephemeral PostgreSQL service, not only static SQL contract checks.
