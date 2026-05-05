# AUDIT REPORT V56 — Operator-action UX gate и recalculate consistency

## Статус до исправления

Проект уже имел корректный server-side запрет `paper_opened` для небезопасных контрактов: действие разрешалось только для actionable `REVIEW_ENTRY`, свежей цены в `entry_zone` и `contract_health.ok=true`. Однако red-team проверка выявила UX/contract drift:

- frontend мог отправить `paper_opened` из устаревшего DOM/состояния, даже если текущий серверный contract уже перешёл в `wait`, `missed_entry`, `expired` или `blocked`;
- backend возвращал техническую строку вроде `paper_opened_allowed_only_for_review_entry: current_status=wait`, пригодную для тестов и аудита, но плохую для оператора;
- `next_actions` мог содержать `recalculate`, однако frontend-фильтр operator actions не поддерживал эту команду, поэтому следующий шаг был видимым текстом, но не рабочим действием.

## Исправления

### Backend

- В `app/api.py` добавлен публичный `operator_action_gate` для успешного и отклоненного `paper_opened`.
- Для отказов добавлено поле `user_message` с человекочитаемым объяснением: текущий статус, причина запрета и безопасный следующий шаг.
- В metadata recommendation contract добавлены `frontend_supported_operator_actions` и описание того, что `recalculate` — frontend-команда пересчёта, а не торговое действие оператора.

### Frontend

- В `frontend/app.js` добавлен `paperGateState(contract)` — клиентский предохранитель перед POST на API.
- `postOperatorAction('paper_opened')` теперь не отправляет запрос, если текущий contract не проходит локальный mirror server gate.
- Сырые backend-коды отказа преобразуются в торгово-понятные сообщения для оператора.
- Действие `recalculate` стало рабочей кнопкой и вызывает `/api/recommendations/recalculate` с текущими category/symbols/intervals.

### Тесты

Добавлен `tests/test_v56_operator_action_recalculate_and_messages.py`:

- отказ `paper_opened` по статусу `wait` возвращает `operator_action_gate.allowed=false` и `user_message`;
- успешный `paper_opened` возвращает публичный gate snapshot;
- frontend содержит пред-gate, поддержку `recalculate` и вызов `/api/recommendations/recalculate`.

## Проверки

Выполнено:

```bash
python -m compileall -q app
node --check frontend/app.js
python -m pytest -q tests
```

Результат после исправлений: `278 passed`.

## Остаточный риск

- Frontend mirror gate не является источником истины; это только UX-предохранитель. Окончательный запрет по-прежнему делает backend и БД.
- `recalculate` пересчитывает рекомендации по текущему набору symbols/intervals из UI, а не только по одному выбранному signal_id. Это осознанное безопасное допущение: точечный пересчёт одного сигнала потребовал бы отдельного backend contract и миграции истории.
