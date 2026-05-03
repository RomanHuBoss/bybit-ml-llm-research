# Red-team audit V30 — recommendation contract, operator actions and quality segmentation

Date: 2026-05-03

## Scope

Reviewed the end-to-end chain:

- Bybit public market data → `candles`, `liquidity_snapshots`;
- indicators/features → raw strategy signals;
- raw signals → MTF/operator recommendation contract;
- recommendation contract → frontend cockpit;
- expired recommendation → outcome evaluation and quality statistics.

## Findings fixed in this iteration

1. The frontend showed entry/SL/TP and R/R, but the contract did not expose a single backend-owned sizing block for risk amount, notional cap, fee/slippage drag and net R/R. This made future frontend-side duplicated math likely.
2. Recommendation quality endpoint returned aggregate outcomes only. It did not provide practical breakdowns by symbol, strategy/timeframe or confidence bucket.
3. Operator actions in the ticket were mostly navigation/refresh controls. There was no durable audit trail for `skip`, `wait`, `manual_review` or `close as invalidated`.
4. Database constraints already protected direction and SL/TP sides, but additional hygiene was needed for empty signal identity fields and numeric `NaN` values.
5. The UI had no explicit place to persist the operator's decision that a recommendation was skipped, taken into manual review, or closed as stale/invalidated.

## Implemented changes

- Added backend-owned `position_sizing` to the recommendation contract:
  - `risk_amount_usdt`;
  - `position_notional_usdt` capped by `MAX_POSITION_NOTIONAL_USDT` and `START_EQUITY_USDT * MAX_LEVERAGE`;
  - `estimated_quantity`;
  - `margin_at_max_leverage_usdt`;
  - `fee_slippage_roundtrip_pct`;
  - `net_expected_reward_pct`;
  - `net_risk_reward`;
  - `sizing_status`.
- Added `POST /api/recommendations/{signal_id}/operator-action` with strict action values:
  - `skip`;
  - `wait_confirmation`;
  - `manual_review`;
  - `close_invalidated`;
  - `paper_opened`.
- Closing a recommendation as invalidated now writes an `invalidated` recommendation outcome, so it becomes visible in quality statistics.
- Extended `GET /api/recommendations/quality` with segmentation:
  - `by_symbol`;
  - `by_strategy`;
  - `by_confidence_bucket`.
- Added `recommendation_operator_actions` table and indexes.
- Added additional safe-repeatable constraints:
  - `ck_signals_non_empty_identity`;
  - `ck_signals_no_numeric_nan`;
  - `ck_backtest_metric_ranges_v30`.
- Added frontend action buttons in the trade ticket:
  - `Взять в разбор`;
  - `Ждать подтверждения`;
  - `Пропустить`;
  - `Закрыть как неактуальную`.
- Added static/unit regression tests for the V30 contract, migration, API and frontend.

## Validation

Executed:

```bash
python -m pytest -q tests
node --check frontend/app.js
```

Result: all tests passed.

## Remaining deliberate boundaries

- No live order execution was added. The project remains advisory-only.
- No private Bybit API keys are required or stored.
- Position sizing is an operator display contract, not an order placement engine.
