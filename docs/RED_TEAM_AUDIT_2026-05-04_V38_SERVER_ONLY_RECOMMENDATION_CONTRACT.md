# Red Team Audit 2026-05-04 — V38 Server-only recommendation contract

## Найдено

- Frontend уже получал `/api/recommendations/active`, но оставлял аварийный fallback: если серверный `risk_reward` отсутствовал, клиент сам считал `reward / risk` из entry/SL/TP.
- При деградации контракта frontend мог снова использовать старую эвристику `algorithmDecisionFor`: собрать score, применить checklist и визуально повысить raw-сигнал до `РУЧНАЯ ПРОВЕРКА ВХОДА`.
- DB-аудит V37 ловил математически невозможные уровни, но не показывал оператору/админу отдельные классы проблем: чрезмерный TTL, активный LONG/SHORT конфликт по одному рынку/бару, отсутствие объяснительного payload и MTF-контекста.

## Исправлено

- Контракт повышен до `recommendation_v38`.
- Каждая рекомендация несёт `decision_source=server_enriched_contract_v38` и `frontend_may_recalculate=false`.
- `contract_health` проверяет, что frontend-перерасчёт запрещён, что top-level `is_actionable` невозможен без зелёного server price gate, и что факторы объяснения представлены структурированными массивами.
- `frontend/app.js` больше не считает `reward / risk`, не использует `Math.abs(entry - stop)` для рекомендации и не имеет `legacy_fallback`.
- При отсутствии server-enriched recommendation contract frontend показывает защитное `НЕТ ВХОДА`, а не пытается самостоятельно классифицировать raw-сигнал.
- Добавлена миграция `20260504_v38_server_only_recommendation_contract.sql`.
- `GET /api/system/warnings` переведён на `v_recommendation_integrity_audit_v38`.

## DB guardrails V38

- `ck_signals_directional_ttl_upper_bound_v38` ограничивает срок жизни directional-рекомендации 32 днями от рыночного бара.
- `enforce_signal_recommendation_contract_v38()` заменяет active trigger и сохраняет все строгие directional-проверки V37.
- `v_recommendation_integrity_audit_v38` дополнительно выявляет:
  - `ttl_too_long`;
  - `low_risk_reward_active`;
  - `missing_explanation_payload`;
  - `missing_timeframe_context`;
  - `active_direction_conflict`.

## Проверки

```bash
python -m pytest -q
node --check frontend/app.js
python run.py check
```

Результат текущего прогона: `210 passed`.
