# V54 audit: quote freshness, deterministic quality drawdown, operator next action

## Scope

Аудит выполнен как дополнительная red-team проверка уже существующей advisory-only торговой СППР. Проект не добавляет автоматическую торговлю и не подключает private Bybit API. Изменения направлены на устранение рассинхрона между freshness-контрактом рекомендаций, quotes endpoint, quality drawdown и действиями оператора.

## Найденные дефекты

### Critical / High

1. `/api/quotes/latest` использовал `MAX_SIGNAL_AGE_HOURS` для признака свежести цены. Это опасное смешение TTL торговой идеи и актуальности reference price: 15m котировка могла выглядеть `fresh` в течение часов, хотя recommendation contract уже блокирует stale price по правилу `2 бара + 5 минут`.
2. Recommendation-level drawdown в `/api/recommendations/quality` строился без явного `signal_id` в последующем окне `peak_r`. При нескольких исходах с одинаковым `evaluated_at` порядок R-кривой мог стать недетерминированным на стороне PostgreSQL.
3. UI показывал список `next_actions`, но не имел отдельного server-owned `primary_next_action`; оператору приходилось интерпретировать порядок действий самостоятельно.

### Medium

1. `/api/system/warnings` не публиковал отдельный аудит freshness последних котировок по рынкам/таймфреймам.
2. README не описывал V54-правило: freshness quotes endpoint должен совпадать с interval-aware freshness рекомендаций, а не с research TTL.

## Внесенные исправления

- `/api/quotes/latest` теперь возвращает `market_freshness`, `age_seconds`, `max_age_seconds`, `freshness_reason`, `data_status` по тому же interval-aware правилу, что и recommendation contract.
- `_quality_drawdown_payload` стал детерминированным: R-кривая и peak считаются по `ORDER BY evaluated_at, signal_id`.
- Добавлен `operator_next_action_v54`: каждый outbound recommendation contract теперь содержит `primary_next_action` и список `next_actions`.
- Для actionable `REVIEW_ENTRY` основное действие — `paper_opened`, но описание явно фиксирует, что это только аудируемая paper-отметка и не отправка ордера на Bybit. Список действий сохраняет `manual_review` для обратной совместимости старых frontend/tests.
- `contract_health` проверяет наличие `primary_next_action`.
- Frontend показывает `primary_next_action.label/detail` в главном trade ticket и визуально выделяет первый пункт списка действий.
- Добавлена миграция `20260505_v54_quote_freshness_and_quality_drawdown.sql` с audit-view `v_market_quote_freshness_audit_v54`, view `v_recommendation_quality_drawdown_v54` и contract-view `v_recommendation_contract_v54`.
- `/api/system/warnings` добавляет предупреждения из `v_market_quote_freshness_audit_v54`, если миграция применена.

## Проверки

Выполнено:

```bash
python -m compileall -q app
node --check frontend/app.js
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python run.py check
```

Результат полного набора: `272 passed`.

Дополнительно проверено через FastAPI TestClient:

- `/` возвращает frontend HTML;
- `/api/status` деградирует без PostgreSQL с `ok=false`, не падает HTTP 500;
- `live_trading=false`.

## Оставшиеся риски

- В sandbox не поднимался реальный PostgreSQL и не выполнялась миграция на живой БД; SQL добавлен как repeatable-safe, но production-применение нужно выполнить через `python run.py migrate`.
- Bybit public API не вызывался в ходе финальной проверки, чтобы тесты оставались воспроизводимыми и не зависели от сети/rate limits.
- Система остаётся advisory-only; для production-терминала всё ещё желателен websocket/mark-price feed без автоматического исполнения.
