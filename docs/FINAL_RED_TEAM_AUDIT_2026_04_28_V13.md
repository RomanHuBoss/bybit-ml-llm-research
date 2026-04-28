# Финальный red-team audit v13 — Bybit advisory trading СППР

Дата: 2026-04-28

## 1. Карта проекта

- Backend/core: Python modules в `app/`, API-контракт в `app/api.py`, PostgreSQL helpers в `app/db.py`.
- Trading logic: `app/strategies.py`, `app/recommendation.py`, `app/mtf.py`, `app/safety.py`, `app/research.py`.
- Bybit integration: `app/bybit_client.py`, только public market endpoints.
- Background loops: `signal_background`, `backtest_background`, `llm_background`.
- Frontend: `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`, Vanilla JS/CSS.
- Tests: pytest/static regression tests в `tests/`.
- Docs/config: `.env.example`, `README.md`, `docs/`.

## 2. Состояние до исправлений

Проект уже содержал несколько hardening-слоев: stale-bar filtering, MTF consensus, lazy DB import, advisory-only UI, фоновые контуры signal/backtest/LLM/ML. При повторной проверке выявлены оставшиеся boundary-риски: строковые булевы флаги могли обходить veto/eligibility-контроль, absolute R/R мог отображаться без явной directional-validity диагностики, а raw table frontend не имела фактической сортировки по ключевым торговым колонкам.

## 3. Состояние после исправлений

- MTF veto теперь безопасно интерпретирует boolean-like значения из JSON/API/DB boundary.
- Liquidity eligibility в strategy layer больше не использует `bool("false")`.
- Safety layer маркирует directional validity SL/TP и отдельный directional R/R.
- Frontend raw table получила сортировку, keyboard accessibility и aria-sort.
- README приведен к фактической архитектуре и advisory-only ограничениям.
- Добавлены regression-тесты для новых safety/UI случаев.

## 4. Найденные проблемы по критичности

### Critical

1. **Boolean boundary для MTF veto.** Если `mtf_veto` или `higher_tf_conflict` приходили строкой `"true"`, старая проверка `is True` могла не включить hard-veto. Исправлено в `app/recommendation.py`.
2. **Liquidity eligibility как строка.** В `app/strategies.py` строка `"false"` могла стать truthy через `bool(value)`. Исправлено через `_boolish`.

### High

1. **Directional R/R диагностика.** Absolute R/R мог быть рассчитан даже при перепутанных SL/TP. Hard-veto уже существовал в recommendation layer, но safety/API annotation не показывала отдельный directional status. Добавлены `levels_valid`, `levels_problem`, `directional_risk_reward`.
2. **Raw table без сортировки.** Для оператора критична быстрая сортировка по score/R/R/spread/confidence; UI показывал таблицу, но без интерактивной сортировки. Исправлено.

### Medium

1. README был перегружен историческими ревизиями и расходился с эксплуатационным форматом документации. Переписан структурно.
2. Frontend badge/table hardening требовал отдельного cache-busting v13.

### Low

1. Не все новые diagnostic fields были отражены в документации.
2. Часть проверок окружения нестабильна в контейнере из-за зависаний Python/pytest runner.

## 5. Исправления

- `app/recommendation.py`: boolean-like MTF veto/higher conflict parsing.
- `app/strategies.py`: safe bool parsing для `is_eligible`.
- `app/safety.py`: directional SL/TP validation и directional R/R annotation.
- `frontend/index.html`: sortable table headers, cache version v13.
- `frontend/app.js`: raw table sorting state, sorters, aria-sort, keyboard handlers.
- `frontend/styles.css`: визуальные состояния sortable headers, focus ring, badge hardening.
- `tests/test_operator_recommendation.py`: regression на строковые MTF veto-флаги.
- `tests/test_core_safety.py`: regression на directional level validity.
- `tests/test_frontend_decision_ui.py`: static regression на sortable table.
- `README.md`: актуальная инструкция запуска, архитектура, ограничения и risk disclaimer.

## 6. Оставшиеся риски

- Нет live PostgreSQL/Bybit/Ollama проверки в контейнере.
- Полный pytest/run.py check в текущей среде зависал на уровне Python/runner, поэтому полный зеленый прогон не подтвержден именно здесь.
- Нет account-state reconciliation и WebSocket execution layer; это ожидаемо, так как система advisory-only.
- ML/LLM evidence не должен трактоваться как торговый приказ.

## 7. Принятые допущения

- `REVIEW_ENTRY` означает только ручную проверку, не автосделку.
- При неопределенном liquidity статусе система должна оставаться консервативной.
- Stale определяется по рыночной свече `bar_time`, а не по свежести записи `created_at`.
- Optional evidence может снижать оценку, но hard-veto принадлежит risk/freshness/MTF/levels/liquidity слоям.

## 8. Проверки

Выполнено:

- `node --check frontend/app.js` — успешно.
- Targeted Python compile для измененных core/test файлов — выполнен через `python -S` и `py_compile`; измененные файлы компилировались без синтаксических ошибок.
- Targeted direct core checks для `classify_operator_action`, `directional_risk_reward`, `annotate_signal_row` — ожидаемые результаты получены.
- Static search по frontend ids — ранее проверено, отсутствующих `$('id')` для HTML id не выявлено.

Не удалось надежно выполнить:

- `python -m pytest -q tests` — timeout/hang в текущем контейнере.
- `python run.py check` — timeout/hang в текущем контейнере.
- Live PostgreSQL/Bybit/Ollama checks — сервисы не поднимались в среде аудита.

## 9. Security/advisory-only проверка

По коду не внедрялась логика private order execution. Система остается советующей: public market ingestion, signal generation, evidence/ranking и операторский UI без автоматической отправки ордеров.
