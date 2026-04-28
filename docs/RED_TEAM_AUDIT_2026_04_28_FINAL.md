# Финальный red-team аудит Bybit Research Lab — 2026-04-28

## Карта проекта

- Backend: Python + FastAPI, модульная структура `app/`.
- Frontend: Vanilla HTML/CSS/JS в `frontend/`, dark-mode operator cockpit.
- Storage: PostgreSQL, схема в `sql/schema.sql`.
- Интеграции: публичные Bybit V5 REST endpoints, sentiment sources, optional Ollama-compatible LLM.
- Торговый режим: strictly recommendation-only. В проекте не обнаружена логика автоматической отправки ордеров на биржу.
- Ключевые модули: `bybit_client.py`, `strategies.py`, `mtf.py`, `research.py`, `signal_background.py`, `backtest.py`, `llm_background.py`, `api.py`.
- Точки входа: `run.py`, `app/main.py`, frontend `/`.

## Состояние до правок

Проект уже содержал значительный предыдущий audit-pass: closed-candle ingestion, MTF-veto, Bybit retry/backoff, background signal/backtest/LLM loops, dark trading UI и тесты. Дополнительная проверка выявила residual production-safety риски в import-time устойчивости и выдаче stale-сигналов в API/research витринах.

## Найденные проблемы по критичности

### Critical

1. **Stale-рекомендации могли попадать в `/api/signals/latest` и `/api/research/rank` при свежем `created_at`.**
   Даже если построение новых сигналов уже проверяло `bar_time`, старые/мигрированные/ручные строки в `signals` могли пройти через витрины по свежему `created_at` или без явного `bar_time`-контроля.

### High

1. **DB C-extension импортировался на старте модулей.**
   В поврежденной среде `psycopg2` может зависнуть или упасть на импорте до того, как приложение успеет показать понятную диагностику. Это ломает API-import, frontend static serving и unit-тесты без фактической необходимости обращаться к БД.

### Medium

1. **Frontend freshness-check был привязан к `created_at`.**
   UI мог называть сигнал свежим по времени записи, хотя критичным является возраст закрытой рыночной свечи.
2. **Отсутствовал единый lightweight safety-модуль для аннотации сигналов.**
   Freshness/risk-reward были размазаны между стратегиями и UI.

### Low

1. Документация не фиксировала новый уровень защиты `bar_time` в публичных витринах.
2. Не было regression-тестов именно на API/research suppression stale rows.

## Что исправлено

- `app/db.py`: реализована ленивая загрузка `psycopg2`, `Json`, `RealDictCursor`, `execute_values`; пароль остается маскированным в диагностике.
- `app/safety.py`: добавлен отдельный модуль safety-аннотаций сигналов.
- `app/api.py`: `/signals/latest` теперь отбрасывает строки без `bar_time`, фильтрует stale/unclosed по `bar_time` и добавляет freshness/risk-reward поля.
- `app/research.py`: `/research/rank` больше не ранжирует сигналы без `bar_time` и дополнительно фильтрует stale rows перед MTF consensus.
- `frontend/app.js`: checklist и queue используют `fresh/data_status/bar_closed_at/signal_age_minutes`, если они пришли из API; fallback по `created_at` сохранен.
- `README.md`: добавлено описание финальной ревизии, выполненных проверок и ограничений среды.

## Что добавлено

- `app/safety.py`.
- `tests/test_db_lazy_import.py`.
- `tests/test_recommendation_freshness_api.py`.
- `docs/RED_TEAM_AUDIT_2026_04_28_FINAL.md`.

## Торгово-логические ошибки

- Закрыто: риск показа stale-сигнала как актуального кандидата.
- Закрыто: отсутствие `bar_time` больше не допускается в latest/rank витринах.
- Остаточный риск: качество стратегии и thresholds зависят от фактических рыночных данных и требуют walk-forward/forward paper validation на реальной БД.

## Архитектурные ошибки

- Закрыто: import-time зависимость на DB C-extension.
- Остаточный риск: FastAPI startup все равно зависит от установленных backend-зависимостей; для production нужен отдельный health/static fallback или контейнеризация.

## Backend/Core ошибки

- Закрыто: DB errors теперь возникают в момент DB-access, а не при импорте модуля.
- Закрыто: API/research rows получают единые `fresh`, `data_status`, `signal_age_minutes`, `risk_reward`.

## Frontend/UI/UX ошибки

- Закрыто: UI freshness-check теперь использует серверную оценку актуальности рыночной свечи.
- Сохранено: dark-mode trading cockpit, operator queue, MTF, checklist, LLM, news, technical details.
- Остаточный риск: полноценный TradingView/lightweight-charts график не подключался; текущая карта сделки остается canvas/placeholder-контуром.

## JavaScript-ошибки

- Проверен синтаксис `frontend/app.js` через `node --check`.
- Добавлена graceful-логика: если API еще не отдает freshness-поля, frontend остается совместимым с прежним `created_at` fallback.

## Надежность и отказоустойчивость

- Усилено: DB driver lazy loading.
- Усилено: API-level stale suppression.
- Остаточный риск: live PostgreSQL/Bybit/Ollama в контейнере не проверялись.

## Тестовое покрытие

Добавлены тесты:

- lazy DB import без загрузки `psycopg2` до реального подключения;
- suppression stale/no-bar-time rows в `app.safety`;
- suppression stale rows в `/signals/latest`;
- suppression stale rows в `research.rank_candidates_multi`.

Проверки, выполненные в контейнере:

```bash
node --check frontend/app.js
python -S -m py_compile app/db.py app/safety.py app/api.py app/research.py tests/test_db_lazy_import.py tests/test_recommendation_freshness_api.py
```

Полный `pytest` не был надежно завершен из-за ограничения контейнера: обычный `python` зависает на global site initialization, а `pytest` import становится недетерминированным. Это не трактуется как успешный full-test pass.

## Конфигурация и запуск

- `.env.example` оставлен совместимым.
- API-контракты не ломались; добавлены только дополнительные поля freshness/risk-reward в ответах сигналов.
- Live-order execution не добавлялся.

## Безопасность

- Секреты не добавлялись.
- Диагностика PostgreSQL по-прежнему маскирует пароль.
- Автоматическая торговля не внедрялась.

## Принятые допущения

1. Сигнал без `bar_time` опасен для оператора и должен подавляться в торговых витринах.
2. Свежесть рекомендации определяется временем закрытия бара + допустимым лагом, а не временем записи строки `created_at`.
3. При сбое DB-драйвера допустима деградация до понятной ошибки на DB-access, но не import-time зависание всего приложения.
