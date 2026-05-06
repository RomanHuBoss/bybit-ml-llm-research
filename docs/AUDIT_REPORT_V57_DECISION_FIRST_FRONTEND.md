# V57 — decision-first frontend audit and repair

## Найдено

- Главный экран показывал много одинаково важных панелей; оператору приходилось искать ключевое действие среди telemetry, ticket, LLM и таблиц.
- Короткое действие оператора не было вынесено в отдельный верхнеуровневый блок.
- Подробный разбор рекомендации не был отделен от основного экрана в отдельный диалог.
- `/api/system/warnings` не проверял полноту UI-контракта для decision-first отображения.

## Исправлено

- Добавлен блок `Operator next action` с entry/SL/TP/RR/confidence/TTL и коротким объяснением.
- Добавлен topbar-chip `Next`, чтобы текущее действие было видно независимо от прокрутки.
- Добавлен диалог подробностей решения с вкладками `Сводка`, `Risk`, `Факторы`, `История`.
- Добавлена миграция и schema-view `v_operator_decision_first_ui_contract_v57`.
- `/api/system/warnings` теперь сначала использует V57 audit view, а затем прежние integrity views.

## Принятое допущение

Frontend не рассчитывает торговую математику. Он только отображает server-owned recommendation contract и превращает серверные статусы в человекочитаемое действие.

## Hotfix 2026-05-06: SQL compatibility

При проверке реального применения миграции V57 выявлен дефект совместимости схемы: audit-view ошибочно ссылалась на несуществующие поля `signals.signal_score` и `signals.active`. Исправлено:

- `signal_score` удалён из CTE, потому что view не использует это поле;
- активность рекомендации определяется так же, как в существующем контракте проекта: `direction IN ('long','short')`, `bar_time IS NOT NULL`, `expires_at > NOW()` и отсутствие terminal outcome в `recommendation_outcomes`;
- добавлены regression-assertions, запрещающие возвращение `signal_score` и `active IS TRUE` в V57 migration.
