# AUDIT REPORT V48 — Market price freshness guard

## Краткое резюме

Проект уже имел развитый advisory-only recommendation contract, server-side price gate, loss quarantine, quality segments и frontend trading cockpit. В ходе V48-аудита найден оставшийся сквозной риск: `expires_at` ограничивал срок жизни торговой идеи, но не доказывал свежесть reference price, по которой backend определяет `entry_zone`, `moved_away` и `price_actionability`.

Исправление выполнено как совместимое расширение без смены публичного контракта `recommendation_v40`.

## Найденная проблема

**Critical/high:** потенциальный `REVIEW_ENTRY` мог иметь активный TTL и корректные entry/SL/TP, но использовать старый `last_price` или price timestamp без явного freshness-бюджета. Для ручной торговой СППР это опасно: оператор может увидеть валидный сетап, хотя текущая цена уже фактически не подтверждена свежим market-data feed.

## Что исправлено

- Добавлен runtime guard `market_price_freshness_v48` в `app/trade_contract.py`.
- `price_freshness` теперь учитывает возраст `last_price_time` / `bar_time` / legacy fallback и блокирует stale reference price.
- `price_actionability.reason` получает конкретные причины `price_timestamp_too_old`, `missing_price_timestamp`, `price_timestamp_in_future`.
- Nested `recommendation` публикует `market_freshness`, `last_price_age_seconds`, `last_price_max_age_seconds`.
- Серверный `operator_checklist` получил пункт `market_freshness`.
- Frontend показывает `Market freshness` в ticket detail и telemetry через `marketFreshnessText`.
- `/api/recommendations/contract` публикует `market_freshness_extension` и `market_freshness_audit_view`.
- `/api/system/warnings` сначала пробует `v_recommendation_integrity_audit_v48`.
- Добавлена repeatable SQL-миграция `20260505_v48_market_price_freshness_contract.sql`.

## Добавленные тесты

`tests/test_v48_market_freshness_contract.py` покрывает:

1. stale reference price блокирует `REVIEW_ENTRY`, даже если TTL активен;
2. свежий reference price оставляет `REVIEW_ENTRY` actionable;
3. API metadata, SQL schema/migration и frontend публикуют V48-расширение.

## Результаты проверки

- `python -m pytest -q` → 243 passed.
- `node --check frontend/app.js` → OK.
- `python run.py check` → 243 passed, Syntax OK: 99 Python files.

## Оставшиеся ограничения

- V48 всё ещё использует latest candle close как reference price. Для production-терминала желательно добавить отдельный websocket/mark-price feed и reconciliation, но без автоматического исполнения ордеров.
- SQL-аудит V48 использует DB `NOW()` и latest candle; runtime использует API row fields. Это намеренно: audit view ловит DB-состояние, runtime блокирует фактический outbound contract.
