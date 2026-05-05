# Audit Report V46 — Server Actionability and Price Gate Demotion

## Краткое состояние до исправлений

Проект уже имел зрелый advisory-only контур: FastAPI API, PostgreSQL-модель, MTF/veto/quality gates, nested `recommendation` contract V45 и dark-mode trading frontend. Полей и функций автоматической отправки ордеров Bybit не обнаружено: система остается советующей.

Главный найденный дефект V46: сервер мог сохранить `recommendation_status=review_entry` и `trade_direction=long/short` для сетапа, где текущая цена уже вышла из точной entry-zone, но еще не считалась `moved_away`. `price_actionability` и `contract_health` при этом правильно блокировали вход, однако статус и заголовок рекомендации оставались directional. Для оператора это опасный UX/contract conflict: карточка одновременно выглядела как ручной вход и как заблокированный price gate.

## Краткое состояние после исправлений

V46 делает price gate частью server-side статуса, а не только дополнительной подсказкой. Если `price_status` равен `extended` или `moved_away`, directional `REVIEW_ENTRY`/`RESEARCH_CANDIDATE` демотируется в `missed_entry` с `trade_direction=no_trade`. Если текущая цена неизвестна, directional review демотируется в `wait`/`no_trade` до восстановления quote feed. UI теперь получает непротиворечивый контракт: ручной разбор доступен только при `entry_zone`, `contract_health.ok=true` и приемлемом net R/R.

Публичная версия совместимости сохранена как `recommendation_v40`; новый слой опубликован как compatible extension `server_actionability_v46`.

## Найденные проблемы по критичности

### Critical

- Не выявлено автоматической торговли, отправки private orders или хранения trading secrets в коде.

### High

- `review_entry` мог оставаться направленным при `price_status=extended`, хотя серверный `price_actionability` уже запрещал вход до ретеста.
- Отсутствующая текущая цена (`price_status=unknown`) не демотировала directional review в безопасный `WAIT/NO_TRADE` статус.

### Medium

- `/api/recommendations/contract` и `/api/recommendations/active` не публиковали слой server-side actionability V46.
- SQL-аудит не показывал активные сигналы, по которым latest price уже вышла за серверную entry-zone.
- Frontend fallback-текст описывал V45 nested levels, но не фиксировал, что actionability также нельзя пересчитывать на клиенте.

### Low

- Label `NO_TRADE · ENTRY УШЁЛ` был слишком узким: для `extended` правильнее говорить `ждать ретест`, а не обязательно считать сделку окончательно упущенной.

## Торгово-логические ошибки

- Цена вне entry-zone — не trading entry, даже если MTF, confidence и strategy quality выглядят приемлемо.
- `extended` раньше блокировал `is_actionable`, но не менял directional status. Теперь `review_entry` существует только при `price_status=entry_zone`.
- `unknown` price теперь не оставляет `long/short` в операторском статусе: это `WAIT/NO_TRADE` до получения свежей цены.

## Архитектурные ошибки

- Price gate был вторичным полем, а должен быть частью канонического server decision contract.
- API metadata не отражала фактический actionability-порядок.

Исправление: `recommendation_status()` теперь выполняет demotion до построения final contract; UI, nested contract, `contract_health`, `next_actions` и `no_trade_reason` получают единое состояние.

## Backend/core ошибки

Изменены:

- `app/trade_contract.py`: добавлена демоция `extended/moved_away → missed_entry/no_trade`, `unknown → wait/no_trade`, уточнено объяснение `missed_entry`, добавлено `compatible_extensions`.
- `app/api.py`: metadata, summary и warnings переведены на `server_actionability_v46`; audit fallback теперь ищет `v_recommendation_integrity_audit_v46` первым.

## PostgreSQL / целостность данных

Добавлена миграция `20260505_v46_server_actionability_and_price_gate.sql`:

- индекс `idx_signals_active_price_gate_v46` для активных directional-сигналов;
- view `v_recommendation_integrity_audit_v46`, которая расширяет V45 и выявляет активные сигналы, где latest price уже за пределами серверной entry-zone;
- view `v_recommendation_contract_v46`, публикующая правило: `REVIEW_ENTRY` требует валидные уровни, неистекший TTL, `price_status=entry_zone` и `net_risk_reward>1`.

`sql/schema.sql` синхронизирован с новой миграцией для чистой установки.

## Frontend/UI/UX ошибки

- Fallback-сообщение обновлено: frontend не пересчитывает не только R/R, но и actionability.
- Метка `missed_entry` заменена на `NO_TRADE · ЖДАТЬ РЕТЕСТ`, чтобы не провоцировать догон рынка.
- Guardrails-текст уточняет `entry-zone price gate`.

## JavaScript-ошибки

- `node --check frontend/app.js` пройден.
- Новая логика не добавляет глобальных обработчиков, raw JSON или client-side recomputation торгового решения.

## Надежность и отказоустойчивость

- Unknown quote feed больше не может оставить directional review entry.
- Price drift за пределами entry-zone теперь диагностируется и в runtime, и в SQL audit view.
- `NO_TRADE` остается нормальным безопасным состоянием, а не ошибкой интерфейса.

## Тестовое покрытие

Добавлены/обновлены tests:

- `tests/test_v46_server_actionability.py` — demotion для `RESEARCH_CANDIDATE` вне entry-zone, metadata/schema/API публикация V46, summary extension list.
- `tests/test_recommendation_contract_v37.py` — `extended` теперь становится `missed_entry/no_trade`, а не `review_entry` с красным gate.
- `tests/test_recommendation_contract_v32.py` — unknown price демотируется в `wait/no_trade`.
- `tests/test_recommendation_contract_v28.py` — базовый actionable fixture теперь явно содержит свежую цену.
- `tests/test_recommendation_contract_v31.py` — next action для действительно actionable fixture соответствует ручному разбору.
- `tests/test_recommendation_contract_v29.py` — frontend label обновлен под V46.

Результаты проверки:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
237 passed in 7.50s

node --check frontend/app.js
OK

python -m compileall -q app run.py install.py
OK

/usr/bin/timeout 30s python run.py check
237 passed in 5.50s
Syntax OK: 97 Python files
EXIT:0
```

## Расхождения кода и документации

README обновлен: добавлен V46 слой, новая миграция, новые тесты и правило server-side actionability. Документация по V40/V43/V44/V45 расширена до V46 без смены публичной версии контракта.

## Конфигурация и запуск

Новые переменные окружения не требуются. Для существующей БД применить:

```bash
python run.py migrate
```

Для новой БД свежий `sql/schema.sql` уже содержит V46 objects.

## Безопасность

- Автоматическая торговля не добавлялась.
- Private Bybit API не добавлялся.
- Секреты и API keys не добавлялись.
- Frontend не получил права пересчитывать направление, R/R или actionability.

## Оставшиеся риски

- В среде архива не проверялась реальная PostgreSQL-БД с live Bybit market data; проверены unit/static/API-contract/syntax сценарии.
- Полная browser-console проверка требует локального запуска FastAPI и ручного открытия UI.
- OHLC-модель по-прежнему не знает внутрисвечный путь; SL/TP ambiguity остается консервативно `SL-first`.
