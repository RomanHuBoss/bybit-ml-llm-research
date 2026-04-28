# Red-team audit revision — 2026-04-28

## Scope

Аудит выполнен для советующей Bybit СППР: backend/core, Bybit public REST client, торговая генерация рекомендаций, MTF-витрина, frontend trading cockpit, тестовый контур и документация.

Система намеренно остается recommendation-only: live order placement, position management и automated bot creation в проект не добавлялись.

## Project map

- `app/main.py` — FastAPI entrypoint, static frontend, lifecycle фоновых сервисов.
- `app/api.py` — REST endpoints: sync market/sentiment, signals, research rank, backtest, ML, LLM, news, status.
- `app/bybit_client.py` — публичный Bybit V5 REST client, retries/backoff, ingestion candles/funding/OI/liquidity.
- `app/strategies.py` — торговые стратегии, валидация сигналов, persistence.
- `app/mtf.py` — 15m entry + 60m bias + 240m regime/veto consensus.
- `app/backtest.py`, `app/backtest_background.py` — backtest и фоновое обновление доказательств.
- `app/llm*.py` — Ollama-compatible локальная LLM-оценка.
- `app/signal_background.py` — фоновый контур universe → market/sentiment → signals → downstream checks.
- `frontend/index.html`, `frontend/styles.css`, `frontend/app.js` — dark-mode operator trading terminal.
- `tests/` — unit/regression tests for trading safety, frontend contracts, Bybit resilience, MTF, runtime, background workers.

## Critical / high findings fixed

### 1. Fresh `created_at` could mask stale market data

Before fix, a stale DB snapshot could be recalculated into a new signal. The UI would see a fresh `created_at`, while the underlying `bar_time` could be old.

Fix:

- Added `is_market_snapshot_fresh()` in `app/strategies.py`.
- `build_latest_signals()` now rejects missing/future/stale `bar_time` before any strategy can emit a recommendation.
- Added regression tests in `tests/test_stale_market_safety.py`.

Risk reduction: prevents false fresh recommendations after broken market sync, stale database state, or partial ingestion.

### 2. Bybit `result.list` type was trusted too much

Before fix, market endpoints returned `result.get("list", [])` without validating type. A malformed gateway payload with `list` as object/string could flow into downstream loops.

Fix:

- Added `_result_list()` in `app/bybit_client.py`.
- kline, funding, open-interest and tickers now fail closed with `BybitAPIError` on non-list payloads.
- Added regression test in `tests/test_bybit_client_resilience.py`.

Risk reduction: prevents silent partial market state and misleading empty/garbled recommendations.

### 3. Test runner was not reproducible by plain `pytest`

Before fix, `pytest` could fail on `ModuleNotFoundError: app` depending on invocation path and environment.

Fix:

- Added `pytest.ini` with `pythonpath = .` and `testpaths = tests`.

Risk reduction: test execution now matches documented `python run.py check` and CI/local shell behavior.

## Frontend/UI findings fixed

- Technical details block normalized to stable `<details class="panel technical-details" id="technicalDetails">` contract.
- Operations panel opens by default with correct `aria-expanded="true"` and visible “Свернуть панель” affordance.
- Dark-mode trading terminal tests were updated to match actual required style, replacing stale light-fintech assertions.
- Added `.support-grid` styling and redundant safety CSS for equal heights/scrolling of queue, ticket and MTF panels.
- Busy guard keeps navigation and tabs interactive; only API action buttons with `data-busy-lock="true"` are disabled.

## Tests added or updated

Added:

- `tests/test_stale_market_safety.py`
  - stale last market bar returns no signals;
  - recent closed bar can emit signals and assigns `bar_time`.
- `test_bybit_market_list_endpoints_reject_non_list_payload()`
  - malformed Bybit `result.list` fails closed.

Updated:

- `tests/test_frontend_decision_ui.py`
  - renamed and aligned frontend redesign test to dark-mode trading terminal requirements.

## Verification results

Executed:

```bash
node --check frontend/app.js
python -m compileall -q app
python run.py check
```

Result:

```text
68 passed
```

Also verified direct imports:

```text
import app.main
import app.api
```

## Checks not fully executed

- Real PostgreSQL connection and schema migration were not executed in this isolated container.
- Real Bybit network sync was not executed; Bybit behavior is covered by unit/mocked resilience tests.
- Real Ollama/LLM inference was not executed; background LLM state and serialization are covered by existing tests.
- Browser rendering was not executed in a real browser; JS syntax and DOM-contract regression tests were executed.

## Remaining risks

- Recommendation quality still depends on real data completeness, latency, exchange API availability and operator discipline.
- Backtest evidence is not a guarantee of future profitability.
- Full browser E2E and real database integration should be added before institutional production use.
- No live execution module exists by design; any future execution integration must include reconciliation, durable outbox, kill-switch, idempotency, rate limits and audit log.
