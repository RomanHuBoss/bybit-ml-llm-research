# Bybit ML/LLM Research Lab

Локальная исследовательская система для Bybit: сбор рыночных данных, автоотбор ликвидных пар, расчёт признаков, бэктестинг стратегий, ML-ранжирование сетапов, бесплатный sentiment pipeline, LLM-резюме и paper-research.

Проект рассчитан на Windows 11 x64 и Linux, PostgreSQL, Python и фронтенд на Vanilla JS/CSS/HTML. Docker не используется. Для установки и запуска добавлены кроссплатформенные `install.py` и `run.py`.

> Важно: проект не отправляет реальные ордера. Live-trading отсутствует намеренно. Система предназначена для исследования, отбора статистически проверяемых сетапов и paper-trading.

## Что реализовано

### Backend

- Python + FastAPI.
- PostgreSQL storage.
- Bybit V5 public REST client.
- Модуль ликвидности и dynamic symbol universe.
- Модуль стратегий.
- Бэктестинг с комиссиями/slippage.
- ML-модель на sklearn.
- LLM-интеграция через Ollama-compatible endpoint.

### Frontend

- Vanilla JS/CSS/HTML.
- Без React/Vue/Bootstrap.
- Дашборд:
  - управление синхронизацией;
  - dynamic/hybrid universe;
  - latest signals;
  - research ranking;
  - equity curve;
  - новости/сентимент;
  - LLM brief.

### Symbol universe

Добавлен гибридный механизм выбора инструментов:

```text
CORE_SYMBOLS + dynamic top by liquidity
```

Учитываются:

- 24h turnover;
- open interest value;
- bid/ask spread;
- listing age;
- excluded stablecoin pairs;
- eligibility-фильтры.

Основные параметры `.env`:

```env
SYMBOL_MODE=hybrid
CORE_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,BNBUSDT,ADAUSDT,SUIUSDT,AAVEUSDT,LINKUSDT,AVAXUSDT,LTCUSDT,NEARUSDT,1000PEPEUSDT,HYPEUSDT
MIN_TURNOVER_24H=20000000
MIN_OPEN_INTEREST_VALUE=15000000
MAX_SPREAD_PCT=0.05
MIN_LISTING_AGE_DAYS=45
```

### Sentiment без CryptoPanic

CryptoPanic теперь не нужен для работы проекта.

Бесплатный pipeline:

```text
Alternative.me Fear & Greed
GDELT DOC API
RSS: CoinDesk / Cointelegraph
Market-derived sentiment: funding + OI + trend + volume
Local LLM через Ollama
```

CryptoPanic оставлен как optional plugin:

```env
USE_CRYPTOPANIC=false
CRYPTOPANIC_TOKEN=
```

### Стратегии

- Donchian/ATR trend breakout.
- EMA pullback trend-following.
- Bollinger/RSI mean reversion.
- Volatility squeeze breakout.
- Funding extreme contrarian.
- Open Interest trend confirmation.
- Sentiment fear/greed reversal.
- Regime adaptive combo.
- ML ranking.

### ML-признаки

```text
ret_1, ret_3, ret_12, ret_24
EMA gaps
RSI
ATR%
Bollinger position/width
realized volatility
volume_z
funding_rate
oi_change_24
sentiment_score
news_sentiment_score
micro_sentiment_score
liquidity_score
spread_pct
```

### Research ranking

`GET /api/research/rank` объединяет:

- confidence сигнала;
- последний backtest по `symbol + strategy`;
- profit factor;
- Sharpe;
- win rate;
- max drawdown penalty;
- последний ROC AUC ML-модели;
- liquidity score;
- spread penalty.

Это главный слой отбора кандидатов для paper-trading.

## Архитектура

```text
bybit_ml_llm_research_lab/
  app/
    main.py              # FastAPI + static frontend
    api.py               # HTTP endpoints
    bybit_client.py      # Bybit V5 public data client
    symbols.py           # liquidity snapshots + dynamic universe
    research.py          # candidate ranking
    db.py                # PostgreSQL helpers
    indicators.py        # RSI, ATR, Bollinger, EMA, Donchian
    features.py          # feature matrix for ML
    strategies.py        # rule-based + regime adaptive combo
    backtest.py          # sequential backtest engine
    ml.py                # sklearn training/inference
    sentiment.py         # Fear&Greed, GDELT, RSS, CryptoPanic optional, market sentiment
    llm.py               # Ollama-compatible client
    init_db.py           # DB bootstrap
    config.py            # environment config
  frontend/
    index.html
    styles.css
    app.js
  sql/
    schema.sql
  install.py            # кроссплатформенная установка: venv + requirements + optional init-db
  run.py                # кроссплатформенный запуск: server/init-db/test/check/doctor
  scripts/
    setup_windows.ps1
    run_windows.ps1
    init_db.ps1         # legacy PowerShell helper'ы для Windows
  docs/
    SENTIMENT.md
    STRATEGIES.md
    WINDOWS_SETUP.md
  tests/
    smoke_test.py
```

## Быстрый старт Windows/Linux

### 1. PostgreSQL

Создайте БД и пользователя. Команды одинаковы по смыслу для Windows/Linux, выполняются в `psql` от пользователя с правами администратора PostgreSQL:

```sql
CREATE USER bybit_lab_user WITH PASSWORD 'change_me';
CREATE DATABASE bybit_lab OWNER bybit_lab_user;
GRANT ALL PRIVILEGES ON DATABASE bybit_lab TO bybit_lab_user;
\connect bybit_lab
GRANT ALL ON SCHEMA public TO bybit_lab_user;
ALTER SCHEMA public OWNER TO bybit_lab_user;
```

### 2. Установка Python-зависимостей

Windows PowerShell / CMD:

```powershell
python install.py
```

Linux/macOS shell:

```bash
python3 install.py
```

`install.py` создает `.venv`, ставит зависимости из `requirements.txt` и, если `.env` отсутствует, создает его из `.env.example` без перезаписи существующего файла.

### 3. `.env`

Проверьте параметры PostgreSQL и остальные настройки в `.env`:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=bybit_lab
POSTGRES_USER=bybit_lab_user
POSTGRES_PASSWORD=change_me
```

### 4. Инициализация БД

```bash
python run.py db-check
python run.py init-db
```

Альтернативно можно выполнить установку и инициализацию одной командой, если PostgreSQL уже создан и `.env` корректен:

```bash
python install.py --init-db
```


Если на Windows при `init-db` появляется `UnicodeDecodeError: 'utf-8' codec can't decode byte ...`, это обычно не ошибка `schema.sql`, а маскировка исходной ошибки подключения PostgreSQL в локальной кодировке Windows. Сначала выполните:

```bash
python run.py db-check
```

Затем проверьте через `psql` тот же хост, порт, базу и пользователя. Для локальной разработки лучше использовать ASCII-пароль без кириллицы и сохранить `.env` в UTF-8.

### 5. Запуск

```bash
python run.py
```

Эквивалентно:

```bash
python run.py server
```

Открыть:

```text
http://127.0.0.1:8000
```

### 6. Проверка проекта

```bash
python run.py check
```

Команды `run.py`:

```text
python run.py server          # backend + frontend через uvicorn
python run.py init-db         # применить sql/schema.sql
python run.py test            # pytest -q
python run.py check           # compileall + pytest -q
python run.py doctor          # диагностика путей, .env и параметров запуска
python run.py db-check        # проверка подключения к PostgreSQL
```

PowerShell helper'ы в `scripts/` сохранены для совместимости, но основной путь запуска теперь кроссплатформенный.

## Рекомендуемый рабочий процесс

1. `Sync universe` — обновить ликвидность Bybit и выбрать hybrid universe.
2. `Sync market` — загрузить свечи, funding и open interest.
3. `Sync sentiment` — загрузить Fear&Greed/GDELT/RSS и рассчитать market_microstructure.
4. `Build signals` — построить rule-based сигналы.
5. `Backtest` — проверить стратегию на истории.
6. `Train ML` — обучить модель ранжирования.
7. `Rank candidates` — выбрать кандидатов для paper-trading.
8. `LLM brief` — получить риск-ориентированное объяснение сигнала.

## Ollama / LLM

```env
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.1:8b
```

Для NVIDIA RTX 3060 12GB обычно разумно начинать с 7B/8B quantized моделей. LLM используется только для классификации/объяснения, а не для самостоятельного принятия торговых решений.

## API endpoints

```text
GET  /api/status
POST /api/symbols/liquidity/sync
GET  /api/symbols/liquidity/latest
POST /api/symbols/universe/build
GET  /api/symbols/universe/latest
POST /api/sync/market
POST /api/sync/sentiment
GET  /api/sentiment/summary
POST /api/signals/build
GET  /api/signals/latest
GET  /api/research/rank
POST /api/backtest/run
POST /api/ml/train
GET  /api/ml/predict/latest
POST /api/llm/brief
GET  /api/equity/latest
GET  /api/news/latest
```

## Ограничения

- Live-trading не включён.
- Сентимент — шумный источник; использовать только как фильтр/усилитель.
- Бэктест без walk-forward может переоценивать качество стратегии.
- Комиссии, funding, spread и slippage критичны для маленького капитала.
- Любой сигнал должен проходить risk-check и ручную проверку перед реальными деньгами.

## Что можно улучшить дальше

- Walk-forward validation по рыночным режимам.
- Optuna-подбор параметров стратегий.
- WebSocket-стриминг Bybit.
- Портфельный риск-модуль.
- Read-only подключение аккаунта для оценки реальных комиссий.
- Отдельный live-trading модуль только после аудита и kill-switch.

## Production-hardening после аудита v2.1

Проект был усилен в сторону безопасного research/paper-рекомендателя. Он по-прежнему **не отправляет реальные ордера**, не создаёт ботов автоматически и не должен интерпретироваться как автономный торговый исполнитель.

### Критичные изменения безопасности

- Бэктест больше не входит по цене уже закрытой сигнальной свечи. Сигнал формируется на закрытой свече, а исполнение моделируется по `open` следующей свечи с учётом `SLIPPAGE_RATE`.
- Equity curve теперь учитывает mark-to-market по открытой позиции, а не только реализованный PnL. Это делает drawdown более консервативным.
- Если в одной свече достигнуты и stop-loss, и take-profit, бэктест выбирает stop-loss. Это намеренно консервативное допущение из-за неизвестного внутрисвечного порядка цен.
- Добавлены лимиты позиции: `MAX_POSITION_NOTIONAL_USDT` и `MAX_LEVERAGE`. Размер сделки ограничивается не только риском до stop-loss, но и предельным notional.
- Стратегии по умолчанию блокируются, если нет подтверждённого liquidity snapshot или инструмент не прошёл фильтры ликвидности. Управляется `REQUIRE_LIQUIDITY_FOR_SIGNALS=true`.
- Core symbols больше не обходят фильтры ликвидности молча. Для ручного override нужен явный флаг `ALLOW_UNVERIFIED_CORE_SYMBOLS=true`.
- PreLaunch-инструменты Bybit исключаются из universe.
- Funding и open interest синхронизируются chunk/page-подходом, чтобы не терять историю из-за лимита API.
- Bybit REST client получил retry/backoff для transient HTTP/status/retCode ошибок и явную обработку не-JSON ответов.
- Сигналы дедуплицируются по `category + symbol + interval + strategy + direction + bar_time`, чтобы повторный `Build signals` не создавал серию одинаковых рекомендаций.
- ML target больше не маркирует последние `horizon_bars` строк как отрицательный класс, если будущая доходность ещё неизвестна.
- Research ranking использует только свежие сигналы (`MAX_SIGNAL_AGE_HOURS`) и штрафует сигналы без ликвидности/с малым числом сделок в бэктесте.

### Новые настройки `.env`

```env
POSTGRES_CONNECT_TIMEOUT_SEC=5
BYBIT_TIMEOUT_SEC=30
BYBIT_MAX_RETRIES=4
BYBIT_RETRY_BACKOFF_SEC=0.75
ALLOW_UNVERIFIED_CORE_SYMBOLS=false
MAX_POSITION_NOTIONAL_USDT=1000
MAX_LEVERAGE=2
REQUIRE_LIQUIDITY_FOR_SIGNALS=true
MAX_SIGNAL_AGE_HOURS=48
MAX_SYMBOLS_PER_REQUEST=50
MAX_SYNC_DAYS=730
ML_MAX_CPU_COUNT=
```

### Миграция БД

`sql/schema.sql` теперь содержит backward-compatible DDL:

```sql
ALTER TABLE signals ADD COLUMN IF NOT EXISTS bar_time TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS ux_signals_bar_dedup
ON signals(category, symbol, interval, strategy, direction, bar_time)
WHERE bar_time IS NOT NULL;
```

Для существующей базы достаточно повторно выполнить:

```bash
python run.py init-db
```

На старой Windows-схеме также можно использовать legacy helper:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\init_db.ps1
```

### Тесты

Добавлены unit/scenario-тесты для:

- удаления незамаркированного хвоста ML dataset;
- блокировки сигналов без проверенной ликвидности;
- ограничения notional размера позиции;
- входа бэктеста на следующей свече, а не на сигнальной;
- валидации символов;
- retry после transient Bybit retCode `10006`;
- исключения unverified core symbols из universe;
- базового smoke-теста индикаторов;
- отсутствия pandas runtime warning в DB/feature pipeline;
- runtime-настройки `LOKY_MAX_CPU_COUNT` до импорта sklearn/joblib.

Запуск:

```bash
python run.py test
```

или напрямую:

```bash
python -m pytest -q
```

Ожидаемый результат текущей ревизии: `18 passed`.

### Оставшиеся ограничения

- Это research/paper-рекомендатель, а не execution engine.
- Нет WebSocket reconciliation, account-state reconciliation и exchange-side order idempotency, потому что live orders отсутствуют.
- Для реального исполнения нужен отдельный модуль с read-only/account sync, kill-switch, order lifecycle FSM, durable outbox, idempotency keys, circuit breakers и пост-трейд аудитом.
- Profitability не доказана. Перед любым capital-at-risk обязательны walk-forward, out-of-sample, sensitivity analysis по комиссиям/slippage/funding и проверка по нескольким рыночным режимам.

## Runtime-предупреждения pandas на Windows

Если в старой сборке при `Build signals` или `Research rank` появлялись повторяющиеся сообщения вида:

```text
UserWarning: pandas only supports SQLAlchemy connectable ...
FutureWarning: Downcasting object dtype arrays on .fillna ...
```

обновленная версия устраняет их на уровне кода:

- `query_df` больше не вызывает `pandas.read_sql_query` с raw `psycopg2` connection;
- `is_eligible` в feature frame приводится через nullable boolean и затем к обычному `bool`;
- отсутствие liquidity snapshot остается безопасным состоянием `False`, то есть сигнал не должен считаться ликвидным без доказательства.

Ожидаемый результат текущей ревизии:

```bash
python run.py check
python run.py test
```

Ожидаемый результат полного прогона после обновления: `18 passed`.

## Runtime-предупреждение joblib/loky на Windows

Если при `Train ML` появляется сообщение вида:

```text
UserWarning: Could not find the number of physical cores ...
[WinError 2] Не удается найти указанный файл
wmic CPU Get NumberOfCores /Format:csv
```

это не падение обучения: endpoint может завершиться `200 OK`, но `joblib/loky` на Windows пытается вызвать отсутствующую утилиту `wmic` для определения физических ядер. Текущая ревизия задает `LOKY_MAX_CPU_COUNT` до импорта `sklearn/joblib`, поэтому warning подавляется без отключения ML.

По умолчанию используется число логических ядер `os.cpu_count()`. Для ручного ограничения можно указать в `.env`:

```env
ML_MAX_CPU_COUNT=4
```

Если одновременно задан системный `LOKY_MAX_CPU_COUNT`, он имеет приоритет. Проверить видимые настройки можно командой:

```bash
python run.py doctor
```

Ожидаемый результат полного прогона после обновления: `18 passed`.
