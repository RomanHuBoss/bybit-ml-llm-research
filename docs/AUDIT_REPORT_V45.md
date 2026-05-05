# Audit Report V45 — Nested Trade Contract and Signal Payload

## Краткое состояние до исправлений

Проект уже содержал зрелую V44-архитектуру советующей СППР: FastAPI backend, PostgreSQL migrations, dark-mode trading frontend, strategy quality, MTF/veto/risk gates и regression tests. Критичного механизма автоторговли в коде не обнаружено: система остается advisory-only.

Главный найденный дефект текущей итерации был не косметическим: серверный top-level response содержал `entry`, `stop_loss`, `take_profit`, но вложенный объект `recommendation`, который является каноническим UI-контрактом, не содержал этих уровней. Это создавало риск рассинхрона: разные клиенты могли читать разные уровни или падать на неполном контракте. Для trading UI это high-risk дефект, потому что entry/SL/TP должны быть атомарной частью самой рекомендации, а не legacy fallback.

## Краткое состояние после исправлений

V45 делает outbound recommendation contract самодостаточным: nested `recommendation` содержит уровни входа, стопа и тейка, price-actionability, risk/reward, confidence, срок действия и health-гварды. Backend валидирует вложенные уровни, frontend отображает их без пересчета, SQL-аудит выявляет неполный structured signal payload, тесты фиксируют контракт.

Публичная строка версии сохранена как `recommendation_v40`, чтобы не ломать уже подключенный frontend/API. V45 опубликована как совместимое расширение `nested_trade_levels_v45`.

## Найденные проблемы по критичности

### Critical

Не выявлено новых дефектов уровня automatic execution или возможности отправки ордеров без подтверждения оператора.

### High

- Вложенный объект `recommendation` не содержал `entry`, `stop_loss`, `take_profit`, хотя UI и README требуют видеть эти уровни как часть рекомендации.
- `contract_health` проверял legacy/top-level состояние слабее, чем канонический nested contract. Это могло пропустить directional-рекомендацию без самодостаточных торговых уровней.

### Medium

- `/api/system/warnings` не имел V45-слоя аудита structured payload.
- SQL-аудит не выделял неполную `signals.rationale`/timeframe-информацию как отдельную диагностируемую проблему.
- Handled LLM background degraded-state выводился через `console.warn`, что засоряло браузерную консоль и выглядело как runtime warning.

### Low

- Документация описывала V44 как последний слой совместимого расширения и не фиксировала nested trade-level contract.

## Торгово-логические ошибки

- Направленный trade contract был не атомарен: уровни сделки находились не там же, где `decision`, `status`, `risk_reward`, `confidence` и `expires_at`.
- Для trading-интерфейса это опасно: оператор может видеть решение из одного объекта, а уровни — из другого fallback-слоя.

Исправление: nested contract теперь содержит уровни, а `contract_health` отвергает `REVIEW_ENTRY`/`RESEARCH_CANDIDATE` без уровней или с неверной геометрией SL/TP.

## Архитектурные ошибки

- Backend сохранял совместимость через top-level legacy-поля, но канонический UI-contract оставался неполным.
- Версионирование контрактов не показывало V45-расширение.

Исправление: сохранена публичная версия `recommendation_v40`, добавлено `compatible_extensions=[..., nested_trade_levels_v45]`.

## Backend/core ошибки

- Усилена функция `contract_health()`.
- `enrich_recommendation_row()` теперь формирует самодостаточный nested объект.
- API metadata и active response объявляют V45 extension.
- System warnings используют V45 audit view с безопасным fallback на V44/V43/V40.

## Frontend/UI/UX ошибки

- Guardrails-блок не показывал явно, что nested contract содержит серверные trade levels.
- Handled degraded-state писал `console.warn`.

Исправление: UI показывает `contract.entry / contract.stop_loss / contract.take_profit`, а обработанное LLM-background состояние пишется в технический UI-log, не в warning-консоль браузера.

## JavaScript-ошибки

- Runtime syntax check `node --check frontend/app.js` пройден.
- Проверено, что `frontend/app.js` больше не содержит `console.warn`.

## Надежность и отказоустойчивость

- Добавлен SQL integrity audit V45 для structured signal payload.
- Миграция идемпотентная и использует `NOT VALID`, чтобы не ломать существующие БД с историческими загрязненными строками.
- API warnings имеют fallback-цепочку, если новая view еще не применена.

## Тестовое покрытие

Добавлены V45 regression tests:

- nested recommendation содержит `entry`, `stop_loss`, `take_profit`;
- невозможный или неполный directional nested contract получает `contract_health.ok=false`;
- API metadata, SQL migration/schema и frontend contract usage публикуют V45 extension;
- frontend не содержит `console.warn`.

Результат проверки в среде разработки:

```text
python -m pytest -q tests/test_v45_nested_trade_contract.py
3 passed

python -m pytest -q tests
234 passed

node --check frontend/app.js
OK

python run.py check
234 passed; Syntax OK: 96 Python files
```

## Расхождения кода и документации

README обновлен: добавлены сведения о V45 nested trade contract, signal payload audit, совместимости публичной версии `recommendation_v40` и новом extension-флаге.

## Конфигурация и запуск

Изменения не требуют новых переменных окружения. Для существующей БД нужно применить миграцию:

```bash
python run.py migrate
```

Для новой БД свежий `sql/schema.sql` уже содержит V45-объекты.

## Безопасность

- Автоматическая торговля не добавлялась.
- Ключи/секреты не добавлялись.
- Frontend не получил права пересчитывать рекомендацию.

## Оставшиеся риски

- В этой среде не был выполнен реальный запуск против live PostgreSQL и Bybit API с сетевыми данными. Проверены unit/API-contract/static/syntax сценарии.
- Полная browser-console проверка в реальном браузере требует локального запуска приложения и ручного открытия UI.
- OHLC backtest по-прежнему не восстанавливает внутрисвечный путь цены; неоднозначные SL/TP-свечи должны трактоваться консервативно.
