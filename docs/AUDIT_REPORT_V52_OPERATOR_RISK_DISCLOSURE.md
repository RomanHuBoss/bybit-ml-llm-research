# V52 audit: operator risk disclosure and paper-trade integrity

## Scope

Проверена цепочка `recommendation contract → API metadata → frontend rendering → system warnings → SQL integrity audit` для советующей Bybit СППР. Цель итерации — убрать двусмысленность между аналитической рекомендацией и приказом на сделку, а также закрыть legacy-путь записи некорректных бумажных сделок.

## Findings before fix

### High

- Outbound recommendation contract не имел обязательного структурированного блока, который объясняет оператору, что система не торгует автоматически и `confidence_score` не является вероятностью прибыли.
- Frontend мог использовать fallback-guardrails для старых ответов без полного server-owned contract, что оставляло риск повторной интерпретации trade math на клиенте.
- Legacy-таблица `paper_trades` не имела достаточных DB CHECK-ограничений на сторону SL/TP относительно `entry` для `long` и `short`.

### Medium

- `/api/system/warnings` не проверял legacy `paper_trades` на очевидно невозможные бумажные входы.
- README описывал V51 server gate, но не фиксировал отдельную политику risk disclosure и запрета клиентского восстановления рекомендаций из legacy-полей.

## Changes implemented

- Добавлено расширение `operator_risk_disclosure_v52` в `app/trade_contract.py`.
- В каждый nested `recommendation` добавлено поле `operator_risk_disclosures`.
- `contract_health()` теперь считает отсутствие disclosure ошибкой для операторских статусов и требует disclosure `advisory_only_no_auto_orders`.
- Empty/no-signal snapshot возвращает explicit `NO_TRADE` с blocking disclosure.
- API contract metadata публикует `operator_risk_disclosure_extension` и `operator_risk_audit_view=v_recommendation_integrity_audit_v52`.
- Frontend показывает `Risk disclosure` и не строит checklist из legacy-полей при отсутствии server-owned contract.
- Добавлена миграция `20260505_v52_operator_risk_disclosure_and_paper_trade_integrity.sql` с CHECK-ограничениями и audit-view V52.
- README обновлен под фактическую V52-архитектуру.

## Assumptions

- `paper_trades` остается audit/paper таблицей, а не каналом исполнения.
- `flat` допускается как не directional бумажное состояние, поэтому level-side CHECK не применяет LONG/SHORT ordering к `flat`.
- Ограничения добавлены `NOT VALID`, чтобы миграция была безопаснее для БД с историческими legacy-строками; новые записи уже будут проверяться PostgreSQL.

## Verification

- `pytest -q`.
- `node --check frontend/app.js`.
- `python -m compileall -q app tests`.

Live Bybit, реальный PostgreSQL и визуальная проверка браузером должны выполняться в staging/production-like окружении, потому что текущая sandbox-среда не содержит настроенной БД и внешнего браузерного рантайма.
