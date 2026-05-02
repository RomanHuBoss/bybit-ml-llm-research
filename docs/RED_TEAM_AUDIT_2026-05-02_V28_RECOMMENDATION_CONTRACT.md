# Red-team audit V28 — Recommendation Contract & Lifecycle

Дата: 2026-05-02

## Найденные проблемы

1. `/api/signals/latest` отдавал много полезных полей, но не имел единого frontend-ready контракта торговой рекомендации: действие, TTL, price-status, reason/against, invalidation condition и signal breakdown приходилось собирать в разных слоях.
2. `signals` оставался raw-слоем без достаточных DB-инвариантов для confidence, ML probability, timestamp и стороны SL/TP.
3. Не было таблицы результата рекомендации: hit TP, hit SL, expired, invalidated, realized R, MFE/MAE фиксировались только косвенно через backtest trades.
4. Frontend показывал entry/SL/TP и operator decision, но не отображал явно canonical recommendation contract: срок действия, статус цены относительно entry-зоны, действие пользователя и условие отмены.
5. API не имел recommendation-oriented endpoints. Пользователь и UI были вынуждены обращаться к сырому signals API.
6. В `BacktestRequest` был дублирован `interval`.

## Что изменено

1. Добавлен `app/trade_contract.py` — единый слой валидации и обогащения рекомендации.
2. `annotate_recommendations()` теперь сохраняет обратную совместимость старых полей и добавляет nested `recommendation` + плоские поля контракта.
3. Добавлены endpoints:
   - `GET /api/instruments`
   - `GET /api/quotes/latest`
   - `GET /api/recommendations/active`
   - `GET /api/recommendations/history`
   - `GET /api/recommendations/quality`
   - `POST /api/recommendations/recalculate`
   - `POST /api/recommendations/evaluate-outcomes`
   - `GET /api/recommendations/{signal_id}`
   - `GET /api/recommendations/{signal_id}/explanation`
   - `GET /api/system/status`
   - `GET /api/system/warnings`
4. Добавлена миграция `sql/migrations/20260502_v28_recommendation_contract.sql`.
5. `sql/schema.sql` дополнен идемпотентными constraints и `recommendation_outcomes`.
6. Генерация сигналов теперь записывает в rationale risk payload: `risk_pct`, `expected_reward_pct`, `risk_reward`, `invalidation_condition`, `signal_breakdown`, `ttl_bars`.
7. Frontend trade ticket теперь показывает canonical action, trade direction, expires, price status, explanation and invalidation condition.
8. Добавлен outcome evaluator `app/recommendation_outcomes.py`: TP/SL/expired/open/invalidated, realized R, MFE/MAE; при same-bar неоднозначности используется conservative stop-first.
9. Добавлены тесты V28 для математического контракта, API-наличия, SQL-инвариантов, frontend rendering и outcome lifecycle.

## Ключевой контракт рекомендации

Каждая рекомендация после `annotate_recommendations()` содержит:

- `recommendation_status`: `review_entry`, `research_candidate`, `wait`, `blocked`, `expired`, `invalid`;
- `trade_direction`: `long`, `short`, `no_trade`;
- `recommended_action`;
- `entry`, `stop_loss`, `take_profit`;
- `risk_pct`, `expected_reward_pct`, `risk_reward`;
- `confidence_score` 0–100;
- `expires_at` / `valid_until`;
- `price_status`: `entry_zone`, `extended`, `moved_away`, `stale`, `unknown`;
- `recommendation_explanation`;
- `invalidation_condition`;
- `factors_for`, `factors_against`;
- `signal_breakdown`.

## Проверки

Выполнено:

```bash
pytest -q
```

Результат: `164 passed`.
