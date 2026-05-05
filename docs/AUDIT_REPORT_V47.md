# Audit Report V47 — server-owned operator checklist

## Цель итерации

Усилить сквозной контракт `recommendations → API → frontend`, чтобы пользователь видел не только итоговый статус, но и серверный чек-лист принятия решения без повторного расчёта критичных торговых gate на клиенте.

## Карта проекта

- `app/api.py` — FastAPI endpoint-функции и metadata recommendation contract.
- `app/trade_contract.py` — каноническое обогащение рекомендации: identity, уровни сделки, price actionability, TTL, explanation, health, next actions.
- `app/recommendation.py` — классификация операторского решения: `NO_TRADE`, `WAIT`, `RESEARCH_CANDIDATE`, `REVIEW_ENTRY`.
- `app/strategies.py` — генерация raw strategy signals и risk payload.
- `app/recommendation_outcomes.py` — SL-first outcome evaluator для завершённых рекомендаций.
- `sql/schema.sql`, `sql/migrations/*` — repeatable schema/guardrails/views.
- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` — vanilla JS trading cockpit.
- `tests/*` — regression-набор для контракта, backend safety, frontend contract и launcher diagnostics.

## Найденные проблемы

### Critical

Не найдено активной автоматической отправки ордеров; система остаётся advisory-only.

### High

1. Nested recommendation не содержал полного identity-набора `category/symbol/interval/strategy/created_at/bar_time`. Top-level row это имел, но detail/UI могли оказаться зависимыми от legacy fallback.
2. Frontend для чек-листа частично вычислял торговые статусы из отдельных полей (`confidence`, `spread`, `riskReward`, `MTF`) вместо приоритетного отображения server-owned checklist.
3. `contract_health` не считал отсутствие server-owned checklist нарушением API/UI-контракта.

### Medium

1. Metadata публиковала required `symbol`, но nested contract не гарантировал его наличие.
2. SQL contract-view не фиксировал новую обязанность `operator_checklist` и nested identity.

### Low

1. README не описывал V47-расширение server-owned checklist.

## Исправления

- Добавлен `OPERATOR_CHECKLIST_EXTENSION = operator_checklist_v47` и общий список `COMPATIBLE_EXTENSIONS`.
- `enrich_recommendation_row()` теперь добавляет в nested `recommendation`:
  - `category`, `symbol`, `interval`, `strategy`, `created_at`, `bar_time`;
  - `operator_checklist` — серверный список проверок `pass/warn/fail`.
- `contract_health()` теперь проверяет наличие структурированного `operator_checklist`; для `review_entry` требует зелёный `price_gate` в чек-листе.
- `no_trade_decision_snapshot()` получил operator checklist для пустого/защитного состояния.
- `frontend/app.js` добавил `serverChecklistFor()` и сначала отображает server-owned checklist; старый локальный чек-лист оставлен только как fallback для совместимости.
- В ticket detail добавлен блок «Серверный чек-лист».
- Добавлена миграция `20260505_v47_operator_checklist_contract.sql`:
  - `v_recommendation_integrity_audit_v47`;
  - `v_recommendation_contract_v47`.
- `schema.sql` синхронизирован с V47.
- README дополнен разделом V47.

## Принятые допущения

- Публичная версия recommendation contract оставлена `recommendation_v40`, чтобы не ломать существующих потребителей API; V47 добавлена как compatible extension.
- Frontend сохраняет legacy fallback-чеклист для старых ответов, но при наличии `recommendation.operator_checklist` не пересчитывает критичные gate.
- PostgreSQL view не может проверить runtime nested JSON, поэтому V47 view проверяет DB-side prerequisites: identity и полноту stored risk payload в `rationale`.

## Результаты проверки

```text
python -m pytest -q tests
240 passed in 3.72s

node --check frontend/app.js
OK

python run.py check
240 passed in 2.73s
Syntax OK: 98 Python files

python - <<'PY'
import app.api
from app.main import app
print(len(app.router.routes))
PY
api_routes 49
```

## Что не проверялось в sandbox

- Реальный запуск PostgreSQL и применение миграций к живой базе: в среде нет настроенной пользовательской БД.
- Реальные вызовы Bybit API и сетевые rate-limit сценарии: интернет/ключи/живая инфраструктура не использовались.
- Браузерный E2E с реальной консолью: выполнен `node --check`, статические frontend regression tests и API import smoke.

## Остаточные риски

1. Для production-проверки нужна отдельная staging-БД с применением миграций V28–V47 и контрольной выборкой реальных свечей.
2. Outcome evaluator всё ещё использует консервативную OHLC-модель SL-first; для точной внутрисвечной очередности нужны lower timeframe/tick данные.
3. Для полной UI-верификации нужен Playwright/браузерный E2E, которого в проекте пока нет.
