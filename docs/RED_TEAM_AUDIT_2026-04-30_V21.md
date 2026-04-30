# Red-team аудит V21 — institutional decision cockpit и backtest persistence guard

Дата: 2026-04-30  
Контур: Bybit Futures Advisory Research Lab  
Режим: советующая СППР, без автоматической отправки ордеров

## Резюме

V21 закрывает два класса дефектов, обнаруженных при повторной инженерной проверке:

1. **UI/UX торгового решения был недостаточно операторским.** В главной зоне были signal/reasons/meter-блоки, но трейдеру приходилось собирать цену, entry, SL, TP, freshness, veto и expected move из разных участков экрана. Для советующей системы это опасно: оператор может принять решение без мгновенной проверки ключевых уровней и свежести данных.
2. **Backtest persistence path был излишне хрупким в тестовой/maintenance-среде.** После V20 `run_backtest()` создавал хранилище `backtest_trades` перед записью сделок. В production это правильно, но в тестах или аварийной среде с замененным DB-writer отсутствие `psycopg2`/подключения могло ломать уже рассчитанный backtest на idempotent-проверке таблицы.

## Карта проекта

- `app/api.py` — FastAPI endpoint-функции, статус, market sync, signals, research, strategy quality/lab.
- `app/bybit_client.py` — публичный Bybit V5 REST client, retry/backoff, candles/funding/OI/liquidity ingestion.
- `app/features.py`, `app/market_data_quality.py` — загрузка market frame, очистка OHLCV, индикаторы и признаки.
- `app/strategies.py` — генерация технических сигналов и `validate_signal()`.
- `app/mtf.py` — MTF consensus/veto.
- `app/recommendation.py` — канонический операторский verdict: `NO_TRADE`, `WAIT`, `RESEARCH_CANDIDATE`, `REVIEW_ENTRY`.
- `app/operator_queue.py` — стабилизация выдачи: один рынок = один операторский вердикт.
- `app/backtest.py`, `app/backtest_background.py`, `app/strategy_quality.py`, `app/strategy_lab.py` — backtest, quality gate, Strategy Lab.
- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` — Vanilla JS/CSS trading cockpit.
- `tests/` — unit/static/integration regression tests.
- `sql/` — схема и миграции.

## Найденные проблемы по критичности

### Critical

- Новая логика автоматической отправки ордеров не обнаружена. Private Bybit order execution в проекте отсутствует, advisory-only контракт сохранен.
- Неисправленных critical-дефектов, позволяющих проекту самостоятельно торговать, не обнаружено.

### High

- Главный экран не давал оператору за 3–5 секунд единую картину: текущая цена, expected move, entry, SL, TP, freshness, data status, veto и veto reason не были собраны в одном decision-first блоке.
- `run_backtest()` мог завершаться ошибкой на проверке/создании `backtest_trades` в среде без доступного PostgreSQL-драйвера, даже если сам writer был заменен стабом в тесте. Это снижало воспроизводимость и мешало тестировать торговую логику отдельно от инфраструктуры.

### Medium

- Frontend использовал toast tone `warning`, тогда как UI-логика использует `warn`. Из-за этого warning-состояние LLM/background могло отображаться не тем визуальным статусом.
- В market sync был повторный `refreshStatus()`, увеличивавший лишние API-запросы и шум состояния.
- Блок fresh/stale/API degradation существовал, но не был визуально встроен в главный операторский verdict.

### Low

- Не хватало отдельного regression-теста на наличие decision telemetry panel и formatter-функций.
- README не фиксировал V21-изменения: новый cockpit-блок, backtest persistence warning и подтвержденные проверки.

## Исправления

### Backend / Core

- В `app/backtest.py` добавлен безопасный wrapper `_try_ensure_backtest_trades_storage()`.
- `ensure_backtest_trades_storage()` остается штатной idempotent-миграцией для production.
- Ошибка проверки storage теперь возвращается в `persistence_warnings`, а запись сделок всё равно пытается выполниться через основной writer.
- Принятое допущение: если `INSERT backtest_runs` уже успешно прошел или был заменен стабом, сбой проверки структуры `backtest_trades` не должен маскировать результат бэктеста; оператор/инженер получает явное предупреждение.

### Trading logic

- Автоматическая торговля не добавлялась.
- Контракт `NO_TRADE` / `WAIT` / `RESEARCH_CANDIDATE` / `REVIEW_ENTRY` сохранен.
- Directional validation entry/SL/TP и strategy-quality gate не ослаблялись.
- Новый backtest warning не превращает слабый strategy evidence в торговое разрешение; он только фиксирует инфраструктурное состояние persistence layer.

### Frontend / UI / UX

- В `frontend/index.html` добавлен `decisionTelemetry` — компактный блок ключевых параметров решения.
- В `frontend/app.js` добавлены formatter/decision helpers:
  - `volumeFmt()`;
  - `pnlFmt()`;
  - `scoreFmt()`;
  - `riskRewardFmt()`;
  - `currentPrice()`;
  - `expectedMoveText()`;
  - `hardVetoSummary()`;
  - `renderDecisionTelemetry()`.
- Главная decision-zone теперь показывает:
  - текущую цену;
  - expected move;
  - entry;
  - stop-loss;
  - take-profit;
  - freshness;
  - data status;
  - veto;
  - veto reason.
- В `frontend/styles.css` добавлен V21 institutional cockpit layer:
  - более плотная верхняя панель;
  - строгая dark-mode визуальная иерархия;
  - улучшенные KPI-карточки;
  - визуальные states `review/research/watch/reject`;
  - decision telemetry grid;
  - hover/micro-interactions;
  - sticky/hover/направленческая подсветка таблиц;
  - loading skeleton;
  - responsive сетки для desktop/laptop/tablet/mobile;
  - `prefers-reduced-motion` для безопасной деградации анимаций.

### JavaScript

- Исправлен toast tone `warning` → `warn`.
- Удален дублирующий `refreshStatus()` после market sync.
- Добавлены безопасные formatter-функции для отсутствующих, нечисловых или бесконечных значений.
- `renderDecisionTelemetry()` не падает при отсутствии DOM-узла и корректно показывает degraded/unknown значения как `—` или warning, а не как ложный ноль.

### Тесты

Добавлены regression-тесты:

- `test_backtest_trade_storage_migration_failure_is_non_fatal` — проверяет, что сбой idempotent storage migration не ломает результат backtest и возвращает `persistence_warnings`.
- `test_frontend_has_institutional_decision_telemetry_panel` — проверяет наличие V21 decision panel, DOM-id, formatter/helper-функций и CSS-слоя.

## Результаты проверок

Выполнено:

```bash
python -S -c "import sys; sys.path.insert(0, '/opt/pyvenv/lib/python3.13/site-packages'); sys.path.insert(0,'.'); import pytest; raise SystemExit(pytest.main(['-q','tests','--maxfail=10']))"
```

Результат: `127 passed`.

```bash
node --check frontend/app.js
```

Результат: JavaScript syntax check пройден.

```bash
python -S -c "... compileall.compile_dir('app') ... compileall.compile_dir('tests') ..."
```

Результат: Python compileall пройден.

## Что не проверялось полностью

- Live PostgreSQL-инстанс не поднимался в sandbox, поэтому миграции проверены статически и regression-тестами, но не применялись к реальной БД.
- Bybit live API, rate limits и реальные сетевые сбои не прогонялись end-to-end.
- Полная браузерная проверка через Playwright/Chrome DevTools не выполнялась; вместо этого выполнены static UI contract tests и `node --check`.
- Ollama/LLM endpoint не запускался.

## Оставшиеся риски

- Для production/staging нужен отдельный прогон с реальной PostgreSQL БД, применением `sql/schema.sql`/миграций и проверкой `/api/status`, `/api/signals/latest`, `/api/strategies/lab`.
- Нужен браузерный E2E smoke-тест cockpit в реальном viewport 1920/1440/tablet/mobile.
- Без live market-data стенда невозможно доказательно проверить rate-limit поведение Bybit в текущий момент.
- UI по-прежнему не заменяет ручную проверку стакана, проскальзывания, новостей и биржевых ограничений перед сделкой.

## Измененные файлы

- `app/backtest.py` — non-fatal storage guard и `persistence_warnings`.
- `frontend/index.html` — новый блок `decisionTelemetry`, cache-bust JS до V21.
- `frontend/app.js` — formatter/helper-функции, rendering decision telemetry, JS warning/status fixes.
- `frontend/styles.css` — V21 institutional dark-mode cockpit layer.
- `tests/test_core_safety.py` — backtest persistence regression.
- `tests/test_frontend_decision_ui.py` — V21 UI contract regression.
- `README.md` — описание V21 и актуальные проверки.
- `docs/RED_TEAM_AUDIT_2026-04-30_V21.md` — этот отчет.

Удаленных файлов нет.
