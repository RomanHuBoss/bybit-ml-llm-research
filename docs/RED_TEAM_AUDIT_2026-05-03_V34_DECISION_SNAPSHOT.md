# Red-team audit V34 — explicit NO_TRADE decision snapshot and outcome quality metrics

## Найденные проблемы

1. Пустой список `/api/recommendations/active` объяснялся через `market_state`, но не имел канонического recommendation contract. UI был вынужден показывать текстовую empty-state строку, а не полноценное состояние `NO_TRADE`.
2. Версия recommendation contract в summary/market_state отставала от фактического развития API и frontend-контракта.
3. `/api/recommendations/quality` отдавал winrate, average R, PF, MFE/MAE, но не отдавал recommendation-level drawdown и распределение outcome statuses. Пользователь не видел полную картину качества завершённых рекомендаций.
4. DB trigger проверял порядок entry/SL/TP и expires_at > bar_time, но не запрещал запись уже истёкшей directional-рекомендации при INSERT/UPDATE.
5. Frontend при отсутствии кандидатов не показывал структурированную карточку: действие, contract version, price status, confidence, причины и следующие шаги.

## Реализовано

- Добавлен `RECOMMENDATION_CONTRACT_VERSION = recommendation_v34`.
- Добавлен серверный `no_trade_decision_snapshot()` — явный неперсистентный contract для состояния без входа.
- `/api/recommendations/active` теперь возвращает `decision_snapshot`, когда активных рекомендаций нет или API деградировал.
- `/api/recommendations/quality` дополнен:
  - `recommendation_drawdown.max_drawdown_r`;
  - `recommendation_drawdown.cumulative_r`;
  - `recommendation_drawdown.expectancy_r`;
  - `outcome_status_counts`.
- В SQL добавлена миграция `20260503_v34_recommendation_decision_snapshot.sql`:
  - stale-write guard `NEW.expires_at <= NOW()` для directional recommendations;
  - view `v_recommendation_outcome_quality_v34`;
  - индекс `idx_recommendation_outcomes_signal_time_v34`.
- Frontend теперь отображает структурированную `NO_TRADE` карточку вместо пустого блока очереди.
- Добавлены тесты V34 и обновлены contract tests V29/V31 под новую версию contract.

## Проверки

- `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q` → `190 passed`.
- `node --check frontend/app.js` → syntax OK.

## Что осталось на следующие итерации

- Перенести все старые legacy fallback-расчёты frontend в отдельный compatibility module или удалить после подтверждения, что все деплойные backend-версии отдают V34 contract.
- Добавить browser E2E через Playwright, если проект будет разворачиваться как production trading workstation.
- Добавить отдельную витрину по `v_recommendation_outcome_quality_v34` в UI, если нужен полноценный экран постаналитики рекомендаций.
