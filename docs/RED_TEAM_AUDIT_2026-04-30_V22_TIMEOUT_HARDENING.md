# Red-team audit V22 — timeout hardening and Strategy Quality refresh isolation

Дата: 2026-04-30

## Контекст

Операторская ошибка UI: `Ошибка: Strategy quality refreshed. API timeout after 45s: /api/strategies/quality/refresh`.

Причина: frontend запускал тяжелый пересчет `strategy_quality` как обычную синхронную API-операцию с универсальным timeout 45 секунд. Backend endpoint внутри одного HTTP-запроса перебирал до 500 последних backtest-run, для каждого читал сделки/equity evidence и делал upsert. На реальной базе такой расчет закономерно дольше короткого UI-timeout.

## Найденные дефекты

### Critical / High

1. **Долгая аналитическая операция была привязана к HTTP-потоку UI.**
   - Риск: оператор получает ошибку вместо понятного статуса; повторные клики создают нагрузку и гонку пересчетов.
   - Исправление: добавлен `app/strategy_quality_background.py`, endpoint теперь по умолчанию ставит refresh в фоновый сериализованный исполнитель.

2. **Отсутствовал явный статус фонового Strategy Quality refresh.**
   - Риск: невозможно отличить ошибку, долгий расчет и нормальный partial-refresh.
   - Исправление: добавлен `GET /api/strategies/quality/refresh/status`, UI показывает `running / done / error / partial`.

3. **Strategy Quality refresh был неограниченно тяжелым для ручного UI-сценария.**
   - Риск: HTTP timeout, перегрузка PostgreSQL, повторные пересчеты одной и той же матрицы.
   - Исправление: добавлены `STRATEGY_QUALITY_REFRESH_LIMIT` и `STRATEGY_QUALITY_REFRESH_TIME_BUDGET_SEC`; `refresh_strategy_quality()` возвращает `partial=true` при soft-budget.

### Medium

4. **N+1 SELECT по backtest_runs во время refresh.**
   - Риск: лишняя нагрузка на БД и задержки.
   - Исправление: `refresh_strategy_quality()` теперь передает уже выбранную строку в `upsert_strategy_quality_from_run()`; повторный SELECT оставлен только для публичного `upsert_strategy_quality_from_run_id()`.

5. **Ошибки отдельных strategy rows останавливали весь refresh.**
   - Риск: одна поврежденная строка backtest evidence ломает обновление всех остальных стратегий.
   - Исправление: per-row try/catch с `failed`, `errors[]`, продолжением обработки и прозрачной диагностикой.

### Low

6. **README не описывал фактическую деградацию Strategy Quality refresh.**
   - Исправление: документация обновлена: фоновой refresh, status endpoint, настройки лимита и time-budget.

## Внесенные изменения

- `app/strategy_quality.py`
  - добавлен `upsert_strategy_quality_from_run(row)`;
  - `refresh_strategy_quality(limit, time_budget_sec)` стал bounded, partial-aware и per-row fault-tolerant;
  - initial query теперь забирает `equity_curve`, чтобы не читать backtest_runs повторно.

- `app/strategy_quality_background.py`
  - новый сериализованный фоновый исполнитель;
  - повторный запрос во время выполнения складывается в один pending refresh;
  - статус содержит `running`, `pending`, `last_result`, `last_error`, `cycle_no`, настройки бюджета.

- `app/api.py`
  - `POST /api/strategies/quality/refresh` по умолчанию стал non-blocking;
  - добавлен `GET /api/strategies/quality/refresh/status`;
  - синхронный режим оставлен как `wait=true` для диагностики;
  - `/api/status` раскрывает настройки и статус quality refresh.

- `app/config.py`, `.env.example`
  - добавлены `STRATEGY_QUALITY_REFRESH_LIMIT=200`;
  - добавлен `STRATEGY_QUALITY_REFRESH_TIME_BUDGET_SEC=30`;
  - добавлена валидация диапазонов.

- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`
  - кнопка quality refresh больше не ждет завершения тяжелого backend-расчета;
  - добавлен polling статуса;
  - добавлен компактный status badge в Strategy Lab;
  - UI показывает partial/error/running без падения в `API timeout after 45s`.

- `tests/test_strategy_quality_refresh_resilience.py`
  - regression-тест на soft time-budget;
  - regression-тест на non-blocking background service;
  - static frontend-contract тест на новый endpoint/status UI.

## Проверки

Выполнено в ограниченной sandbox-среде:

- `node --check frontend/app.js` — успешно;
- `python -S -m py_compile` для измененных backend-модулей — успешно;
- прямые regression-проверки Strategy Lab и нового Strategy Quality refresh — успешно;
- статическая проверка frontend-контракта нового refresh — успешно.

Полный `python -m pytest -q tests` в sandbox не завершился в лимит времени среды. Причина не была связана с измененным кодом: даже выборочные pytest-прогоны в этой среде зависали/превышали лимит, тогда как прямой импорт и вызов релевантных тестовых функций проходил. На рабочей машине проекта полный pytest нужно запустить по README.

## Оставшиеся риски

- Полная production-эксплуатация по-прежнему требует PostgreSQL monitoring, slow query logging, alerting и внешнего process supervisor.
- Фоновый refresh сериализован внутри одного процесса FastAPI. При многопроцессном uvicorn/gunicorn нужна внешняя job-очередь или DB advisory lock.
- Strategy Quality Gate зависит от качества backtest data; слабый бэктест должен оставлять стратегию в RESEARCH/WATCHLIST, а не насильно превращаться в торговый сигнал.

## Принятые допущения

- Система остается строго advisory-only: новый refresh не отправляет и не может отправлять ордера.
- Для UI безопаснее вернуть `accepted/background` и прозрачный статус, чем держать HTTP-запрос открытым до завершения аналитического пересчета.
- `partial=true` — штатная деградация при большом числе стратегий, не ошибка торговой логики.
