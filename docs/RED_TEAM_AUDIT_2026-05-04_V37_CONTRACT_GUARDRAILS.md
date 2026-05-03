# Red-team audit V37 — contract guardrails and integrity audit

## Найденные проблемы

1. `recommendation_v36` уже отделял серверный контракт от UI, но у активной рекомендации не было отдельного машинно-читаемого отчёта о целостности outbound-контракта. Фронт мог показать `REVIEW_ENTRY`, даже если причина блокировки была только внутри `price_actionability` или net R/R.
2. Price gate допускал состояние `extended` как actionable. Для ручной торговли это рискованно: цена уже вышла из точной entry-зоны, значит оператор должен ждать ретест или пересчёт, а не догонять рынок.
3. Quality gate оценивал gross R/R, но не блокировал сетапы, где после комиссий и проскальзывания net R/R становится непригодным.
4. В БД не было единого audit-view, который быстро показывает legacy/новые строки с нарушением контракта рекомендаций.
5. UI не показывал явный блок `contract_health`, поэтому разработчик/оператор не видел, какая серверная guardrail остановила сделку.

## Что изменено

- Контракт повышен до `recommendation_v37`.
- Добавлен `contract_health` в каждую enriched recommendation: `ok/warn/error`, список guardrail-проблем, версия проверки.
- `price_actionability` теперь считает actionable только `entry_zone`; `extended` требует ждать ретест entry-зоны.
- `classify_operator_action` добавил hard/warn gate по net R/R после fee/slippage.
- UI показывает блок `Guardrails контракта`; кнопка `Взять в разбор` disabled, если `is_actionable=false`.
- `/api/recommendations/active` возвращает summary `contract_guardrails`.
- `/api/system/warnings` подтягивает агрегаты из `v_recommendation_integrity_audit_v37`, если миграция применена.
- Добавлена миграция `20260504_v37_contract_guardrails_and_integrity_audit.sql` и синхронизирован `sql/schema.sql`.

## Практический эффект

`REVIEW_ENTRY` больше не означает автоматически, что прямо сейчас можно входить. Итоговое действие определяется серверным `is_actionable`, где одновременно должны быть зелёными: уровни, TTL, price gate, net R/R и contract health. Это снижает риск входа по цене, которая уже ушла от зоны entry, и делает NO_TRADE/WAIT полноценными состояниями.
