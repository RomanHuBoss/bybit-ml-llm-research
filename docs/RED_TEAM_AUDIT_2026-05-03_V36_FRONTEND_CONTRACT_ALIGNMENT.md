# Red-team audit V36 — frontend contract alignment and price actionability

Date: 2026-05-03
Contract: `recommendation_v36`

## Scope

This pass focused on the remaining cross-module inconsistency after the strict recommendation contract work: backend already returned a validated recommendation contract, but the frontend could still prefer the research rank payload when both rank and active recommendations were loaded.

Reviewed chain:

1. Bybit/market data → candles/latest quote fields.
2. `signals` rows → `annotate_recommendations()` → `enrich_recommendation_row()`.
3. `/api/recommendations/active` → frontend queue/cards/details.
4. Recommendation contract → operator actions and outcome/statistics views.

## Findings

### 1. Frontend source-of-truth drift

`frontend/app.js::candidates()` treated research rank as the primary UI source whenever `state.rank` was non-empty. Because `refreshAll()` loads both rank and `/api/recommendations/active`, this allowed the trading screen to show an enriched research candidate instead of the canonical active recommendation contract.

Impact:

- frontend could show rows whose final trade contract was not the exact active contract payload;
- rank fallback could mask `/api/recommendations/active` fields such as `market_state`, `decision_snapshot`, `expires_at` and outcome filters;
- UI behavior depended on refresh order and array non-emptiness rather than the backend contract.

### 2. Price actionability was implicit

The contract had `price_status` and `is_actionable`, but the detailed reason for price gating was not a standalone payload. The UI could show a price status but did not have a canonical entry window with the exact reason why current price is or is not usable.

Impact:

- moved-away/extended/entry-zone states were harder to explain;
- operator had to infer whether price was still actionable from several fields.

### 3. Frontend duplicated risk math as a first path

The UI still recomputed risk/reward from `entry`, `stop_loss`, `take_profit` before consulting all server-side contract semantics. This was mostly safe because validation existed, but it violated the architecture rule that frontend displays recommendations rather than forming them.

Impact:

- future backend formula changes could drift from UI values;
- legacy fallback and active contract rendering were not clearly separated.

## Fixes implemented

### Backend contract V36

`app/trade_contract.py` now publishes `recommendation_v36` and adds `price_actionability`:

- `status`: `actionable` / `blocked`;
- `is_price_actionable`: boolean;
- `reason` and ordered `reasons`;
- `entry_window.low/high/pct`;
- `last_price`, `price_status`, `price_drift_pct`;
- `checked_at` and `expires_at`.

`is_actionable` is now based on the server price gate rather than repeating the price status set inline.

### API contract metadata

`app/api.py` now exposes:

```text
GET /api/recommendations/contract
```

The endpoint publishes the active contract version, source-of-truth endpoint, allowed statuses/directions/price statuses and required fields. `/api/status` and `/api/system/status` include the same contract metadata.

### Frontend alignment

`frontend/app.js` now uses `/api/recommendations/active` as the primary source for trading cards/details. Research rank is only a fallback when active recommendations are empty or unavailable.

Risk/reward rendering prefers server contract fields (`risk_reward`, `risk_pct`, `expected_reward_pct`) and only falls back to local arithmetic for legacy `/api/signals/latest` fallback mode.

The detailed ticket renders a `Price gate` block so the operator sees why the current price is actionable or blocked.

### SQL metadata

Migration added:

```text
sql/migrations/20260503_v36_frontend_contract_source_and_price_actionability.sql
```

It creates:

- `v_recommendation_contract_v36` for DB-visible contract metadata;
- `idx_signals_active_source_v36` aligned with active recommendation queries;
- `idx_recommendation_operator_actions_signal_time_v36` for operator action history lookup.

## Verification

Executed successfully:

```bash
python run.py check
node --check frontend/app.js
```

Result:

```text
Syntax OK: 85 Python files
202 passed
```
