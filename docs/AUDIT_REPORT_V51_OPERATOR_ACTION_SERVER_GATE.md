# AUDIT REPORT V51 — server-side operator action gate

## Карта проекта

- `app/main.py` — FastAPI application, CORS, static frontend, lifecycle фоновых контуров.
- `app/api.py` — HTTP/API контракт, чтение рекомендаций, operator actions, diagnostics, quality endpoints.
- `app/trade_contract.py` — серверное обогащение рекомендации: TTL, market freshness, price gate, checklist, health, risk/reward/position sizing.
- `app/recommendation.py`, `app/operator_queue.py`, `app/mtf.py`, `app/strategies.py` — цепочка signal → MTF → operator decision → recommendation contract.
- `app/bybit_client.py` — публичный Bybit REST client с timeout/retry/backoff/concurrency semaphore; private order execution отсутствует.
- `sql/schema.sql`, `sql/migrations/*.sql` — PostgreSQL schema + идемпотентные миграции V28–V51.
- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` — vanilla JS dark-mode operator cockpit V50.
- `tests/` — regression-набор для contract, frontend, Bybit resilience, safety, MTF, DB migrations, quality/outcomes.

## Найденный дефект

### Critical

`paper_opened` был защищен только на уровне frontend disabled-button. Старый или прямой API-клиент мог вызвать `POST /api/recommendations/{signal_id}/operator-action` с `action=paper_opened` для неactionable рекомендации: `missed_entry`, `blocked`, stale price, failed contract health или красный пункт operator checklist. Для советующей trading-СРППР это критично: журнал оператора мог фиксировать бумажный вход там, где серверный contract уже запрещал вход.

## Исправления

1. `app/api.py`
   - добавлен `_paper_entry_rejection_reason()`;
   - добавлен `_operator_action_observed_price()`;
   - `paper_opened` теперь принимается только если server-owned contract имеет:
     - `recommendation_status=review_entry`;
     - `is_actionable=true`;
     - `contract_health.ok=true`;
     - `price_status=entry_zone`;
     - `trade_direction in {long, short}`;
     - нет `fail` в `operator_checklist`;
   - для `paper_opened` обязательна положительная audit price: explicit `observed_price` или server `last_price`;
   - payload operator action теперь хранит `is_actionable`, `contract_health_ok`, `market_freshness`, `price_status`, `net_risk_reward`.

2. `sql/migrations/20260505_v51_operator_action_server_gate.sql`
   - добавлен `ck_recommendation_operator_actions_paper_price_v51`;
   - добавлен `ck_recommendation_operator_actions_paper_status_v51`;
   - добавлен индекс `idx_recommendation_operator_actions_paper_audit_v51`;
   - добавлена audit-view `v_recommendation_integrity_audit_v51`.

3. `sql/schema.sql`
   - актуализирован full schema для новых установок.

4. `app/trade_contract.py`, `app/api.py`
   - добавлено совместимое расширение `operator_action_server_gate_v51`;
   - `/api/system/warnings` теперь сначала использует `v_recommendation_integrity_audit_v51`.

5. `frontend/app.js`
   - `paper_opened` явно маркирован как действие, повторно проверяемое сервером;
   - `manual_review` оставлен доступным для разбора неactionable/research/blocked сетапов, потому что это не вход и не paper execution.

6. `tests/test_operator_action_server_gate_v51.py`
   - добавлены unit/static regression tests на запрет unsafe `paper_opened`, разрешение только actionable REVIEW_ENTRY и наличие SQL/API/frontend V51 contract.

## Проверки

- `python -m pytest -q tests/test_operator_action_server_gate_v51.py` — проходит.
- Полный regression suite должен запускаться командой `python -m pytest -q tests`.
- `node --check frontend/app.js` проверяет JS-синтаксис.

## Оставшиеся риски

- Проект по-прежнему не исполняет реальные ордера и не имеет account reconciliation; это осознанное ограничение советующей СППР.
- Для production-grade paper/live контроля желательно добавить отдельную таблицу paper positions с lifecycle `opened → managed → closed`, но это уже расширение домена, а не дефект текущего operator-action audit.
