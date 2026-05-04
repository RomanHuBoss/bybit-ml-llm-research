# Red-team audit 2026-05-04 — V41 backtest/outcome/frontend TTL hardening

## Контекст

Проверка проведена после сообщения, что на большом массиве свечей система не дала ни одной успешной сделки и что вероятны ошибки в расчетах и обновлении frontend. Проект остается советующей СППР: автоматическая отправка ордеров в этой ревизии не добавлялась и не обнаружена.

## Карта проекта

- `app/bybit_client.py` — публичный Bybit REST, retry/backoff, market-data ingestion.
- `app/features.py`, `app/market_data_quality.py` — загрузка/очистка свечей и расчет признаков.
- `app/strategies.py` — raw strategy signals и проверка уровней.
- `app/mtf.py`, `app/operator_queue.py`, `app/recommendation.py`, `app/trade_contract.py` — MTF/veto, стабилизация очереди и финальный серверный recommendation contract.
- `app/backtest.py`, `app/strategy_quality.py`, `app/recommendation_outcomes.py` — backtest, quality gate, фиксация исходов рекомендаций.
- `app/api.py` — API для cockpit и фоновых операций.
- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` — dark-mode trading cockpit.
- `sql/schema.sql`, `sql/migrations/` — PostgreSQL schema/migrations.
- `tests/` — unit/static/regression tests.

## Найденные дефекты

### Critical

1. **Смещение колонок при записи `backtest_trades`.** Вставка сделок бэктеста содержала лишнее значение `exit_time`, из-за чего tuple не соответствовал списку колонок. На реальной БД это могло ломать сохранение сделок или искажать evidence для `strategy_quality`, что напрямую влияет на статус `APPROVED/WATCHLIST/RESEARCH/REJECTED`.
2. **Бэктест мог догонять цену.** Сигнал строился по расчетному `entry`, но исполнение происходило по следующему `open` без проверки, что цена осталась в допустимой зоне входа. Это создавало рассинхрон между live-контрактом `price_actionability` и backtest evidence.

### High

1. **Frontend freshness fallback конфликтовал с серверным TTL.** Checklist мог ориентироваться на `created_at`/legacy freshness и недостаточно явно использовать `recommendation.ttl_status`, `expires_at`, `checked_at`, `price_actionability.reasons`.
2. **Регрессионный тест Strategy Lab зависел от отсутствующего файла.** В репозитории отсутствовал `docs/QUALITY_SNAPSHOT_2026-04-30.json`; полный `pytest` падал, а значит критерий воспроизводимой проверки проекта не выполнялся.

### Medium

1. **`backtest_trades` не имел достаточных DB guardrails в актуальной схеме.** Направление, цены и порядок времени должны быть защищены на уровне БД, а не только Python-кода.
2. **Индекса под quality/outcome lookup по `symbol/strategy/direction/exit_time` не было в базовой схеме.** Это ухудшало проверку похожих исходов и диагностик качества.

### Low

1. README описывал V20 quality snapshot как существующий, но сам JSON-файл отсутствовал.
2. В отчете и README не было явного описания новой backtest entry-drift дисциплины.

## Внесенные исправления

- Исправлена запись `backtest_trades`: tuple теперь строго соответствует колонкам `run_id, symbol, strategy, direction, entry_time, exit_time, entry, exit, pnl, pnl_pct, reason`.
- Добавлена функция `_entry_drift_gate()`: бэктест пропускает сигнал, если следующий executable open ушел от расчетного `entry` дальше допустимой зоны. Зона зависит от ATR и ограничена безопасными пределами.
- `run_backtest()` теперь возвращает `skipped_signals` и сохраняет эту диагностику в `backtest_runs.params`.
- Добавлены DB guardrails для `backtest_trades`: `direction IN ('long','short')`, `entry > 0`, `exit > 0`, `exit_time >= entry_time`.
- Добавлен индекс `idx_backtest_trades_quality_lookup_v41`.
- Добавлена idempotent-миграция `sql/migrations/20260504_v41_backtest_trade_storage_guardrails.sql`.
- Восстановлен `docs/QUALITY_SNAPSHOT_2026-04-30.json` как регрессионный fixture Strategy Lab.
- Frontend checklist теперь приоритетно использует серверный recommendation contract: `ttl_status`, `is_expired`, `expires_at`, `checked_at`, `price_status`, `price_actionability.reasons`.
- Добавлены/усилены regression tests на корректную запись сделок и пропуск входа при уходе цены из entry-zone.

## Принятые безопасные допущения

- Если next-open находится вне entry-zone, бэктест не открывает сделку. Это может уменьшить число сделок, но защищает статистику от недостижимых ручных входов.
- Если в одной OHLC-свече достигнуты SL и TP, система сохраняет консервативное правило stop-first, потому что без tick/order-book последовательности нельзя доказать TP-first.
- Quality snapshot в `docs/` является regression fixture, а не утверждением о реальном live-качестве стратегий.

## Проверки

Выполнено в sandbox:

```bash
node --check frontend/app.js
python -m py_compile app/backtest.py
python -m pytest -q tests --disable-warnings --maxfail=30
python run.py check
```

Результаты:

- `node --check frontend/app.js` — успешно.
- `python -m py_compile app/backtest.py` — успешно.
- `pytest` — `216 passed`.
- `python run.py check` — `Syntax OK: 89 Python files`, `216 passed`.

Не выполнялось:

- Подключение к реальной PostgreSQL и применение миграций к production/staging БД — в sandbox нет пользовательской БД и `.env`.
- Реальный Bybit sync — для воспроизводимого аудита использованы локальные unit/regression проверки без сетевой зависимости.
- Браузерный e2e с devtools console — выполнена JS syntax-проверка; полноценная проверка UI требует запуска приложения в браузере с реальной/тестовой БД.

## Оставшиеся риски

- Для production обязательно применить миграцию V41 к PostgreSQL и прогнать backtest/strategy-quality refresh на реальных данных.
- Если после честного entry-drift gate сделок станет меньше, нужно расширять стратегии и фильтры, а не отключать guardrail.
- Нужен отдельный browser e2e smoke-test после подключения к реальной БД/API.
