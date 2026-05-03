# Red-team audit V35 — Active recommendation integrity

Дата: 2026-05-03

## Найдено

1. `GET /api/recommendations/active` строился из последних строк `signals`, но не исключал рекомендации, по которым уже был зафиксирован terminal outcome (`hit_take_profit`, `hit_stop_loss`, `expired`, `invalidated`, `closed_manual`). В результате UI мог снова показать как активный сетап, который оператор уже закрыл или outcome-evaluator уже завершил.
2. Active-query полагался на `created_at` и `bar_time`, но не требовал `expires_at > NOW()`. Просроченный directional signal мог попасть в активную выдачу и превращался в NO_TRADE только на уровне enrich-контракта.
3. `GET /api/recommendations/quality` и сегменты качества считали `open` outcomes вместе с завершёнными. Это искажало `evaluated`, `winrate`, `profit_factor`, сегменты по инструментам/стратегиям/confidence buckets.
4. История/детальная карточка не имела отдельного нормализованного блока outcome. Пользователь видел уровни и объяснение, но не видел компактно, чем закончилась старая рекомендация.
5. `python run.py check` мог зависать на обёрнутом subprocess-запуске pytest в sandbox/scientific-stack окружении после успешного завершения тестов.

## Исправлено

- Contract bump: `recommendation_v35`.
- Active recommendation API теперь требует `expires_at IS NOT NULL AND expires_at > NOW()` и исключает любой signal с terminal outcome.
- Quality endpoint и сегментные метрики считаются только по `recommendation_outcomes.outcome_status <> 'open'`.
- Добавлен DB-view `v_active_recommendation_contract_v35` — канонический SQL-слой активных directional-рекомендаций.
- Добавлен DB-view `v_recommendation_quality_terminal_v35` — качество только по завершённым рекомендациям.
- Добавлен partial index `idx_recommendation_outcomes_terminal_v35` и active index `idx_signals_active_contract_v35`.
- Добавлен constraint `ck_recommendation_outcomes_terminal_price_v35` для terminal outcome semantics.
- В contract payload добавлен блок `outcome` с terminal-флагом, exit, realized R, MFE/MAE.
- UI карточка деталей показывает блок `Исход рекомендации`.
- Launcher `run.py check` переведён на in-process `pytest.main`, чтобы проверка завершалась детерминированно.

## Проверка

```bash
python run.py check
node --check frontend/app.js
```

Результат в sandbox: `196 passed`.
