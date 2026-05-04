# Red-team audit V39 — TTL clock, hard veto visibility and frontend freshness state

Дата проверки: 2026-05-04  
Режим: советующая торговая СППР для Bybit, без автоматической отправки ордеров.

## Карта проекта

- `app/` — Python/FastAPI backend, конфигурация, Bybit/market-data адаптеры, построение сигналов, recommendation contract, outcome evaluator, health/warnings API.
- `frontend/` — vanilla HTML/CSS/JS trading cockpit. Клиент отображает серверный recommendation contract и не пересчитывает финальную торговую математику.
- `sql/schema.sql` и `sql/migrations/` — базовая PostgreSQL-схема и repeatable/idempotent hardening migrations для сигналов, рекомендаций, outcomes и integrity views.
- `tests/` — pytest regression/unit/contract набор по торговой логике, contract/API/frontend static checks и edge cases.
- `docs/` — отчеты аудита по ревизиям и quality snapshots.
- `run.py` — локальный launcher для install/check/api/ui.

## Найденные дефекты

### Critical

1. **Недетерминированная проверка TTL в тестах и contract enrichment.**  
   Рекомендации из regression-набора с фиксированным `expires_at=2026-05-02` начали считаться истекшими на фактическую дату 2026-05-04. Это не дефект теста как такового: торговый contract не имел единой передаваемой точки времени на всех этапах проверки TTL/price gate/status, поэтому воспроизводимость пограничных сценариев была слабой.

2. **Пограничная рекомендация `expires_at == now` могла расходиться в трактовке.**  
   Для торговой системы граница срока жизни должна быть закрытой: если срок равен текущему времени, вход запрещен. Любая неоднозначность на этой границе опасна, потому что UI может показать устаревший directional-сетап как еще пригодный.

### High

1. **Hard-veto мог быть скрыт статусом expired.**  
   Если рекомендация была `NO_TRADE` из-за MTF/veto, но срок уже истек, оператор мог видеть только истечение TTL и терять исходную причину запрета. Для аудита торгового решения первичная причина hard-veto должна сохраняться.

2. **Frontend не показывал человекочитаемый TTL как отдельное состояние.**  
   UI показывал срок действия, но не давал отдельного состояния `active / expiring / expired / missing`, из-за чего оператору было сложнее за 3–5 секунд понять, можно ли вообще рассматривать рекомендацию.

### Medium

1. **Метаданные recommendation contract не фиксировали новые TTL-поля как обязательные.**  
   API-contract endpoint не требовал `checked_at`, `ttl_status`, `ttl_seconds_left`, хотя эти поля нужны frontend для отказоустойчивого отображения свежести.

2. **`run.py check` зависал в sandbox после syntax phase.**  
   Прямой pytest-прогон проходит, но launcher в данной среде не завершился стабильно. Это снижало надежность диагностического сценария в ограниченных окружениях.

### Low

1. **Версия cache-busting CSS не отражала текущую ревизию frontend.**  
   Браузер мог использовать старый CSS и не показать новые TTL-стили.

## Исправления

### Backend / trading contract

- Добавлена единая функция `utc_now(value=None)` для нормализации времени в UTC.
- Добавлена `ttl_state(expires_at, now=None)` с машинно-читаемыми полями:
  - `status`: `missing`, `expired`, `expiring_soon`, `active`;
  - `seconds_left`;
  - `is_expired`;
  - `checked_at`.
- `enrich_recommendation_row()` теперь вычисляет одну точку `as_of` и использует ее для TTL, freshness, recommendation status и price actionability.
- `expires_at <= now` теперь однозначно блокирует вход как `expired`.
- `NO_TRADE`/hard-veto остается `blocked` даже после истечения TTL, чтобы оператор видел исходную причину запрета.
- В outbound recommendation contract добавлены `checked_at`, `ttl_status`, `ttl_seconds_left`, `is_expired`.
- Empty-state `no_trade_decision_snapshot()` получил такие же TTL-поля, чтобы frontend не делал специальных догадок.

### API contract metadata

- `/api/recommendations/contract` теперь декларирует обязательные TTL-поля:
  - `checked_at`;
  - `ttl_status`;
  - `ttl_seconds_left`.

### Frontend / UI

- Добавлены `ttlText(contract)` и `ttlTone(contract)`.
- TTL отображается в telemetry, execution map, карточках очереди и ticket metrics.
- Добавлены CSS-состояния `.ttl-state.active`, `.ttl-state.expiring`, `.ttl-state.expired`, `.ttl-state.unknown`.
- CSS cache-busting обновлен до `trading-cockpit-v39`.
- Клиент продолжает отображать серверный contract и не пересчитывает торговое решение.

### Tests

- Existing contract tests переведены на фиксированный `TEST_NOW`, поэтому regression-набор больше не зависит от календарной даты запуска.
- Добавлен `tests/test_recommendation_contract_v39.py`:
  1. проверяет закрытую границу `expires_at == now`;
  2. проверяет, что hard `NO_TRADE` не скрывается expired TTL;
  3. проверяет, что API metadata и frontend реально экспонируют TTL-состояние.

### Launcher hardening

- `run.py check` переведен на subprocess pytest с `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` и `PYTHONDONTWRITEBYTECODE=1`, чтобы снизить влияние сторонних pytest plugins и bytecode cache side effects.

## Результаты проверок

Выполнено успешно:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests
# 213 passed in 5.42s

node --check frontend/app.js
# OK

python -m py_compile app/*.py run.py install.py sitecustomize.py
# OK
```

Ограничение среды:

```bash
python -u run.py check
```

В текущей sandbox-среде команда дошла до `Syntax OK: 88 Python files`, после чего subprocess-диагностика не завершилась до timeout. Прямой эквивалентный pytest-прогон выше выполнен и прошел полностью. Перед staging/production нужно повторить `python run.py check` в чистом virtualenv/CI с доступом к обычному процессному окружению.

## Остаточные риски

- Не проверялось live-подключение к реальному PostgreSQL и Bybit API: sandbox не содержит production credentials и рыночного окружения.
- Автоматическая торговля не добавлялась и не активировалась; проект остается advisory-only.
- V39 не меняет версию публичного recommendation contract (`recommendation_v38`), а расширяет его безопасными совместимыми TTL-полями. Это сделано, чтобы не ломать существующие consumer tests и frontend fallback.

## Принятые допущения

- На границе `expires_at == checked_at` рекомендация считается истекшей и не может быть использована для входа.
- Hard-veto/`NO_TRADE` важнее истекшего TTL как основной операторский статус; TTL при этом сохраняется отдельным полем `ttl_status=expired`.
- Frontend имеет право форматировать `ttl_status`, но не имеет права пересчитывать `trade_direction`, `entry`, `SL`, `TP`, `risk_reward`, `is_actionable`.
