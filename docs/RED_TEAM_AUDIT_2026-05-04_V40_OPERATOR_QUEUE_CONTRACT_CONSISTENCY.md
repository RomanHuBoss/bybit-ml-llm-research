# Red-team audit V40 — operator queue / recommendation contract consistency

## Scope

Проверен сквозной путь:

`signals SQL → classify_operator_action → consolidate_operator_queue → enrich_recommendation_row → /api/recommendations/active → frontend/app.js`.

## Critical finding

До V40 порядок обработки был небезопасным:

```text
annotate_recommendations(rows) → consolidate_operator_queue(...)
```

`annotate_recommendations()` сразу строил nested `recommendation` contract. После этого `consolidate_operator_queue()` мог обнаружить материальный LONG/SHORT конфликт и изменить top-level `operator_action` на `NO_TRADE`, но вложенный `recommendation` оставался уже сформированным по старому решению. В UI это могло дать рассинхрон: часть карточки показывала `NO_TRADE`, а часть — `review_entry`.

## Fix

Новый порядок:

```text
ensure_operator_decisions(rows) → consolidate_operator_queue(...) → annotate_recommendations(...)
```

Изменённые места:

- `app/recommendation.py` — добавлен `ensure_operator_decisions()`; `annotate_recommendations()` больше не перетирает уже принятые operator-решения.
- `app/api.py` — `/api/signals/latest` и `/api/recommendations/active` используют consolidation before enrichment.
- `app/research.py` — `rank_candidates_multi()` использует тот же безопасный порядок.
- `app/trade_contract.py` — contract version поднят до `recommendation_v40`, `decision_source=server_enriched_contract_v40`.
- `sql/migrations/20260504_v40_operator_queue_contract_consistency.sql` — опубликованы `v_recommendation_integrity_audit_v40` и `v_recommendation_contract_v40`.
- `frontend/app.js` — статическое правило обновлено до `Frontend v40 не пересчитывает торговое решение`.
- `tests/test_recommendation_contract_v40.py` — regression-test на LONG/SHORT conflict → top-level и nested contract оба `NO_TRADE`.

## Risk reduction

- Фронт больше не может получить противоречивую пару `operator_action=NO_TRADE` + `recommendation.recommendation_status=review_entry` после серверной консолидации.
- Материальный конфликт направлений остаётся hard-veto и попадает в `factors_against` nested contract.
- `is_actionable=false` сохраняется одновременно в top-level и nested contract.
- Contract metadata явно публикует `operator_queue_policy=operator_queue_consolidates_before_contract_enrichment`.

## Verification

```text
pytest -q
215 passed in 4.09s
```

Дополнительные проверки:

```text
node --check frontend/app.js: OK
python -m py_compile app/*.py run.py install.py sitecustomize.py: OK
```

## Remaining risks

- SQL integrity view может видеть только фактические active LONG/SHORT conflicts в БД, но не может проверить runtime nested JSON без выполнения API. Поэтому главный regression guard находится в Python test layer.
- Перед staging нужно применить V40 migration на PostgreSQL и проверить `/api/system/warnings` в реальном окружении.
