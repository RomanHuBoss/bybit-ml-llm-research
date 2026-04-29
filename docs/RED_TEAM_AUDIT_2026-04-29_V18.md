# Red-team audit V18 — Bybit advisory trading DSS

Дата: 2026-04-29  
Режим: советующая торговая СППР, без автоматического исполнения ордеров.

## Карта проекта

- `app/main.py`, `app/api.py` — FastAPI backend и HTTP API.
- `app/bybit_client.py` — публичный REST-клиент Bybit для market-data: candles, funding, open interest, tickers, instruments.
- `app/features.py`, `app/indicators.py`, `app/market_data_quality.py` — очистка OHLCV, индикаторы, feature frame.
- `app/strategies.py`, `app/mtf.py`, `app/recommendation.py`, `app/operator_queue.py`, `app/research.py` — генерация сигналов, MTF consensus, veto/recommendation, очередь оператора и ранжирование.
- `app/backtest.py`, `app/backtest_background.py`, `app/ml.py`, `app/ml_background.py`, `app/llm*.py` — evidence-слои, не являющиеся источником торгового приказа.
- `frontend/index.html`, `frontend/styles.css`, `frontend/app.js` — dark-mode operator cockpit.
- `tests/` — unit/static/regression тесты безопасности, MTF, рекомендаций, Bybit client, frontend contract.
- `.env.example`, `README.md` — конфигурация и инструкция запуска.

## Advisory-only проверка

В проекте не обнаружена логика автоматической отправки ордеров: отсутствуют private Bybit order endpoints, подпись `X-BAPI-*`, `place_order/create_order`, управление позициями и ключами API. `live_trading` в `/api/status` остается `False`. Система выдает только операторскую рекомендацию.

## Найденные и исправленные дефекты

### Critical

1. **Глобальный liquidity snapshot вместо per-symbol snapshot.**
   - Риск: частичный sync одного символа мог сделать liquidity join неверным для всех остальных символов.
   - Исправление: `/api/signals/latest`, `app/research.py` и `app/symbols.py` используют per-symbol latest snapshot и отдельную freshness-проверку по каждому символу.

2. **Доверие устаревшему spread/eligibility в feature-layer.**
   - Риск: старый `is_eligible=true` и узкий spread переносились вперед через `ffill`, что могло разрешить ручной вход по фактически устаревшему стакану.
   - Исправление: добавлен TTL `LIQUIDITY_SNAPSHOT_MAX_AGE_MINUTES`; stale liquidity маркируется как `unknown`, spread становится `999`, score — `0`, eligibility — `False`.

### High

3. **Bybit open-interest без cursor-pagination.**
   - Риск: API-ответы с `nextPageCursor` могли тихо обрезать историю open interest.
   - Исправление: `get_open_interest()` теперь собирает все страницы, сохраняет параметры запроса и ловит cursor-loop.

4. **Несогласованный список стратегий в `/api/status`.**
   - Риск: `trend_continuation_setup` реально существовал и использовался, но не попадал в публичный список стратегий; UI/оператор видел неполную картину.
   - Исправление: стратегия добавлена в `STRATEGY_NAMES`.

5. **Нестабильность операции построения сигналов при недоступной LLM-оценке.**
   - Риск: сигналы могли быть успешно построены, но UI показывал операцию как неуспешную из-за вторичной фоновой LLM-задачи.
   - Исправление: LLM run-now после build signals обернут в безопасный `try/catch`; оператор получает warning, а не ложный fail.

### Medium

6. **Недостаточная диагностичность freshness ликвидности во frontend.**
   - Исправление: checklist теперь показывает `fresh/stale/missing/unknown` для liquidity snapshot.

7. **Non-MTF latest signals не ограничивал SQL-выборку по `MAX_SIGNAL_AGE_HOURS` до сортировки/limit.**
   - Исправление: свежесть внесена в SQL WHERE, чтобы stale-сигналы не вытесняли свежие строки в пределах `LIMIT`.

8. **Тестовая фикстура liquidity использовала старый alias `start_time`.**
   - Исправление: `app/features.py` сохраняет backward-compatible rename `start_time -> liquidity_captured_at` для тестов/старых вспомогательных вызовов.

### Low

9. README и `.env.example` не описывали TTL liquidity snapshot.
   - Исправление: добавлен `LIQUIDITY_SNAPSHOT_MAX_AGE_MINUTES=120`, ревизия V18 и принятое допущение.

## Добавленные и обновленные тесты

- `tests/test_liquidity_freshness.py`
  - stale snapshot больше не подтверждает `is_eligible` и spread;
  - fresh snapshot сохраняет score/spread/eligibility.
- `tests/test_bybit_client_resilience.py`
  - open-interest cursor-pagination;
  - open-interest cursor-loop detection.
- `tests/test_api_contract_static.py`
  - API/research используют symbol-scoped fresh liquidity join;
  - старый `latest_liq_time/MAX(captured_at)` запрещен.
- `tests/test_red_team_advisory_safety_v15.py`
  - обновлен contract-тест liquidity join под безопасный V18 SQL.
- `tests/test_warning_cleanup.py`
  - фикстура обновлена под TTL-aware liquidity.

## Результаты проверок

- `python -S -m py_compile app/config.py app/features.py app/api.py app/research.py app/bybit_client.py ...` — успешно.
- `node --check frontend/app.js` — успешно.
- Полный pytest в активном Python runtime: `119 passed`.

Ограничение среды: обычный shell-запуск Python/pytest в sandbox зависал на platform `sitecustomize`/scientific-stack teardown. Поэтому полный прогон выполнен через активный Python runtime с `--import-mode=importlib -p no:cacheprovider`. Это не меняет тестовую логику проекта, но перед staging/production нужно повторить `pytest -q tests` в чистом virtualenv.

## Оставшиеся риски

- Нет WebSocket/account reconciliation, потому что система не исполняет ордера.
- Нет durable audit log для ручных действий оператора за пределами текущего UI-журнала.
- LLM/ML/backtest evidence остаются вспомогательными и требуют мониторинга свежести.
- Для production нужны внешние алерты по Bybit rate limits, stale market data, PostgreSQL health и задержкам background jobs.
- При добавлении private API в будущем потребуется отдельный execution-модуль с kill-switch, idempotency, reconciliation и запретом исполнения без подтверждения оператора.
