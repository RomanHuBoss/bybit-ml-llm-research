# Red-team аудит V17 торгово-советующей системы Bybit — 2026-04-29

## 1. Карта проекта

- `app/main.py` — FastAPI-приложение, static frontend, startup фоновых сервисов.
- `app/api.py` — HTTP API для статусов, сигналов, rank, LLM/backtest/background операций.
- `app/bybit_client.py` — публичный Bybit V5 market-data клиент, retry/backoff, ingestion свечей/funding/open interest/liquidity.
- `app/market_data_quality.py` — новый слой строгой OHLCV-валидации и очистки DataFrame.
- `app/features.py` — сбор рыночных фичей из PostgreSQL, индикаторы, funding/OI/sentiment/liquidity joins.
- `app/strategies.py` — генерация advisory-сигналов, entry/SL/TP/confidence/rationale и `validate_signal()`.
- `app/mtf.py` — multi-timeframe consensus и veto.
- `app/recommendation.py` — серверная классификация операторского решения `NO_TRADE` / `WAIT` / `REVIEW_ENTRY`.
- `app/operator_queue.py` — стабилизация очереди оператора, дедупликация рынка, защита от близкого LONG/SHORT-конфликта.
- `app/safety.py` — свежесть свечей, диагностика уровней и R/R.
- `app/backtest.py` — локальный backtest стратегий.
- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` — dark-mode trading cockpit.
- `tests/` — unit/static/integration regression tests.
- `README.md`, `docs/` — эксплуатационная документация и отчеты аудита.

## 2. Состояние до V17

Система уже имела V15/V16 hardening: advisory-only контракт, liquidity-state разделение, MTF/veto/risk controls, dark-mode cockpit и regression-набор. Повторная проверка обнаружила дополнительные capital-safety риски:

1. Bybit kline ingestion мог принять физически невозможную свечу, если API/шлюз вернул malformed или численно некорректную строку.
2. `features.load_market_frame()` рассчитывал индикаторы на данных БД без отдельного повторного OHLCV-фильтра, то есть старые/ручные битые строки могли попасть в ATR, RSI, Bollinger и ML-features.
3. Backtest мог симулировать сделку по сигналу, который live/advisory path отверг бы через `validate_signal()`.
4. `profit_factor=None` для бэктеста без убыточных сделок мог быть принят за отсутствие backtest evidence.
5. Frontend-очередь зависела от числового `id`; fallback/rank-строки без id могли терять выбранного кандидата.
6. Несколько прямых JS-привязок к DOM могли уронить интерфейс при измененной/частично загруженной HTML-разметке.

## 3. Состояние после V17

- Добавлен единый модуль строгой проверки OHLCV.
- Bybit ingestion пропускает malformed, unclosed и invalid свечи до записи в БД.
- Feature-layer очищает market frame перед индикаторами.
- Backtest и live/advisory path используют одну и ту же сигнальную валидацию.
- Backtest evidence различает `missing`, `incomplete` и `no_losses`.
- Frontend сохраняет selection через стабильный `symbol|interval` ключ.
- Frontend event/canvas bindings стали graceful при отсутствующих DOM-узлах.
- Документация дополнена V17-допущениями и проверками.

## 4. Найденные проблемы по критичности

### Critical

1. **Невалидные OHLCV-свечи могли искажать рекомендации.** Один `high_below_body`, `low_above_body`, `NaN volume` или отрицательный turnover способен исказить ATR, stop-loss, take-profit, R/R, volatility и confidence. Исправлено в `app/market_data_quality.py`, `app/bybit_client.py`, `app/features.py`.
2. **Backtest/live inconsistency.** Бэктест мог открыть simulated trade по сигналу, который live-рекомендательный контур не пропустил бы из-за невалидного направления или уровней. Исправлено в `app/backtest.py`.

### High

1. **All-win backtest evidence маркировался как missing.** `profit_factor=None` при отсутствии gross loss теперь не равен отсутствию evidence; добавлен reason `backtest_no_losses`.
2. **Frontend мог потерять выбранного кандидата без числового id.** Добавлен fallback-ключ `symbol|interval`.
3. **JS мог падать при отсутствующей кнопке/canvas.** Добавлен безопасный `bindClick()` и guarded canvas rendering.

### Medium

1. **Очистка market-data была распределена по слоям неявно.** Теперь есть единая точка проверки свечей.
2. **Документация не описывала V17-допущения по битым свечам и backtest/live parity.** README и новый отчет дополнены.
3. **Часть проверок в sandbox не воспроизводима как полноценный live-run из-за отсутствия PostgreSQL/.env/браузера.** Риск явно зафиксирован.

### Low

1. **Преимущественно эксплуатационные ограничения:** staging-browser smoke, DB migration smoke и live Bybit rate-limit сценарии требуют внешнего окружения.

## 5. Исправления по направлениям

### Торгово-логические ошибки

- Введена строгая OHLCV-валидация до расчета индикаторов и рекомендаций.
- Backtest теперь пропускает сигнал, если `validate_signal()` возвращает ошибку.
- All-win backtest не считается отсутствующим evidence, но получает предупреждение о размере выборки.

### Архитектурные ошибки

- Валидация рыночных данных вынесена в отдельный модуль и используется в ingestion и feature-layer.
- Сохранена существующая архитектура: API/strategies/recommendation/operator queue не переписаны с нуля.
- Добавлен parity между simulation и advisory-runtime без изменения внешнего API-контракта.

### Backend/Core ошибки

- Защита от malformed Bybit kline rows.
- Защита от незакрытых свечей.
- Защита от `NaN`, бесконечных, отрицательных и физически невозможных OHLCV-значений.
- Защита от поврежденных строк в БД перед `add_indicators()`.

### Frontend/UI/UX ошибки

- Стабильный выбор operator candidate по `symbol|interval` при отсутствии `id`.
- Graceful degradation для отсутствующих кнопок/canvas.
- Сохранена существующая professional dark-mode структура: top bar, left queue, central decision board, execution map, right analytics, bottom tables/log/debug.

### JavaScript-ошибки

- Устранены прямые небезопасные привязки к DOM для основных операций.
- Canvas equity rendering больше не падает при отсутствии `equityCanvas`.
- Queue selection больше не привязан жестко к numeric id.

### Надежность и отказоустойчивость

- Данные с биржи теперь fail-closed: подозрительная свеча пропускается, а не используется для entry/SL/TP.
- Feature-layer повторно чистит БД-данные, даже если ingestion в будущем будет обойден ручным импортом.
- Backtest не завышает качество стратегии за счет сигналов, невалидных для live advisory path.

### Проблемы тестового покрытия

Добавлен `tests/test_market_data_quality.py`:

- rejection физически невозможных свечей;
- rejection `NaN` volume;
- очистка DataFrame от invalid/duplicate bars;
- skip malformed/unclosed/invalid Bybit kline rows в `sync_candles()`.

Обновлен `tests/test_operator_recommendation.py`:

- all-win backtest case получает `backtest_no_losses`, а не `backtest_missing`.

### Расхождения код ↔ документация

- README дополнен ревизией V17.
- Создан отдельный отчет V17.
- Зафиксированы ограничения sandbox-проверки и необходимость staging-прогона.

### Конфигурация и запуск

- Новые правки не требуют новых `.env` переменных.
- `.env.example` не изменялся.
- Сценарий запуска остается прежним: `pip install -r requirements.txt`, PostgreSQL schema, `python run.py app`.

### Безопасность

- Логика автоматической отправки ордеров не добавлялась.
- Изменения сохраняют advisory-only режим.
- Bybit private/order execution path не внедрялся.

## 6. Выполненные проверки

Выполнено успешно:

```text
python -S -m py_compile app/*.py run.py install.py sitecustomize.py
compiled 33

node --check frontend/app.js
OK
```

Ранее в этой sandbox-сессии полный pytest-прогон успел вывести:

```text
113 passed in 1.21s
rc 0
```

После этого среда начала зависать на импорте/завершении Python/pytest-процессов, поэтому результат полного прогона нужно повторить в чистом virtualenv. Targeted/manual проверки нового market-data quality контура выполнялись через прямой вызов тестовых функций и подтвердили ожидаемое поведение валидатора/ingestion.

## 7. Что не удалось проверить

- Живой запуск FastAPI с PostgreSQL: в sandbox нет `.env` и PostgreSQL-инстанса.
- Реальный live Bybit API/rate-limit сценарий: внешняя сеть и ключи не использовались.
- Браузерная консоль и responsive UI в Chromium/Firefox: нет полноценного browser runtime.
- Длительный soak-test фоновых циклов: требует staging-инфраструктуры.

## 8. Оставшиеся риски

1. Провести staging-прогон с реальной БД, заполненными `candles`, `liquidity_snapshots`, `signals`, `backtest_runs`, `llm_evaluations`.
2. Провести browser E2E/smoke для cockpit, responsive layouts и console errors.
3. Проверить live деградации Bybit: 429/rate-limit, пустые ответы, частичные outages.
4. Добавить метрики/alerting по числу пропущенных invalid candles, stale market и background failures.
5. При любом будущем private API создать отдельный модуль исполнения с kill-switch, durable outbox, idempotency, reconciliation и ручным approval workflow.

## 9. Ключевые измененные файлы

- `app/market_data_quality.py` — новый общий слой OHLCV quality gate.
- `app/bybit_client.py` — валидация Bybit kline rows до записи.
- `app/features.py` — очистка market frame перед индикаторами.
- `app/backtest.py` — live/backtest signal validation parity.
- `app/recommendation.py` — корректная трактовка all-win backtest evidence.
- `frontend/app.js` — устойчивый selection и guarded event/canvas bindings.
- `tests/test_market_data_quality.py` — новые safety-регрессии market data.
- `tests/test_operator_recommendation.py` — regression для `backtest_no_losses`.
- `README.md` — ревизия V17.

## 10. Удаленные файлы

Проектные файлы не удалялись. Перед упаковкой удаляются только технические `__pycache__`/`.pytest_cache` артефакты.
