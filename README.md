# Bybit ML/LLM Research Lab

## Red-team ревизия 2026-04-28

Эта ревизия закрывает дополнительные production-safety дефекты, обнаруженные при повторной инженерной проверке советующей СППР:

- `pytest.ini` фиксирует `pythonpath = .`, поэтому тесты воспроизводимо запускаются через `pytest` и `python run.py check` без ручного `PYTHONPATH`.
- `build_latest_signals()` больше не строит свежую рекомендацию на старом последнем баре: проверяется именно `bar_time` закрытой свечи, а не только новый `created_at` сигнала. Если рынок устарел или timestamp отсутствует, система возвращает no-signal/stale-data состояние вместо потенциально опасного входа.
- Bybit public REST client теперь валидирует, что `result.list` действительно является массивом для kline/funding/open-interest/tickers; нестандартный gateway/body не превращается в молчаливый пустой рынок.
- Frontend закреплен как dark-mode trading terminal: открытая операционная панель, LIVE OFF в верхней панели, кандидатская очередь, trade ticket, MTF, LLM, risk/evidence, news и technical details остаются доступными без декоративной навигации.
- Busy guard не блокирует навигацию, вкладки и фильтры; повторный API-запуск отсекается только для `data-busy-lock="true"`.
- Обновлены regression-тесты под фактическую dark trading-верстку и добавлены новые safety-тесты на stale market snapshot и невалидный Bybit `result.list`.

Проверено в текущем контейнере:

```bash
node --check frontend/app.js
python -m compileall -q app
python run.py check
# результат: 68 passed
```

Ограничения проверки: live-подключение к реальной PostgreSQL/Bybit/Ollama в контейнере не выполнялось; проверены импорт приложения, синтаксис JS, compileall и весь локальный pytest-набор с monkeypatch/stub-сценариями.


## Production-safety изменения ревизии 2026-04-26

Проект остается **research/recommendation-only** системой: он не создает live-ордера, не управляет позициями на бирже и не является grid-ботом. Любая интеграция реального исполнения должна быть вынесена в отдельный модуль с account-state reconciliation, idempotency key, durable outbox, kill-switch, лимитами ордеров и пост-трейд аудитом.

Что усилено в этой ревизии:

- Bybit kline ingestion теперь отбрасывает незакрытую текущую свечу. Это исключает рекомендации по бару, где `close` еще является текущей ценой последней сделки, а не финальным закрытием бара.
- transient-коды Bybit дополнены `10429` для system-level frequency protection; retry/backoff остается только для публичных REST-запросов.
- Сохранение backtest-run теперь использует `INSERT ... RETURNING id`, а не `SELECT id ORDER BY id DESC`; это убирает race condition при параллельных запусках.
- Перед сохранением сигналов добавлена проверка непротиворечивости: направление, confidence, entry, ATR и порядок SL/TP. Некорректные рекомендации не попадают оператору.
- Spot liquidity universe больше не требует open interest; inverse universe больше не отбрасывается USDT-фильтром по ошибке.
- Добавлен фоновый контур автоматического обновления рекомендаций: `universe -> market/sentiment -> signals -> backtest/LLM`, без live-order execution.
- Фоновый backtest-runner автоматически поддерживает свежие backtest-доказательства по актуальным `symbol+strategy` и защищен от перекрывающихся запусков.
- Фоновые LLM-циклы больше не используют один и тот же event для shutdown и run-now; остановка и пробуждение разделены.
- `app.api` больше не импортирует тяжелый sklearn/joblib на старте; ML загружается лениво только в `/api/ml/*`.
- RSS/GDELT/CryptoPanic новости без URL получают детерминированный synthetic-key вместо Python `hash()`, чтобы не плодить дубли после рестарта.
- `app.ml` больше не создает каталог `models` при импорте; запись в ФС выполняется только перед фактическим сохранением модели.


### Дополнение: UX/front-end pass

В этой версии фронтенд дополнительно переработан как cockpit оператора, а не как техническая витрина: крупный первичный вердикт, более чистая очередь 15m-кандидатов, локальные scroll-контейнеры, понятные risk/evidence/LLM/news/protocol вкладки и улучшенная адаптивность.

Эксплуатационные защиты UI:

- API-запросы фронтенда имеют timeout через `AbortController`;
- длительные операции блокируют кнопки и не допускают повторного запуска до завершения;
- внешние ссылки новостей проходят whitelist `http/https`;
- class-токены из backend-данных нормализуются;
- кнопки явно заданы как `type="button"`, очередь кандидатов получила `aria-live="polite"`.

Дополнительно Bybit-клиент защищен от нечислового `retCode` и зацикливания cursor pagination, а runtime задает безопасные лимиты потоков BLAS/MKL/NumExpr для локального research-стенда.

Проверка текущей ревизии:

```bash
python -m compileall -q app tests run.py install.py sitecustomize.py
python -m pytest -q tests
```

В текущем контейнере подтверждены `node --check frontend/app.js`, `python -m compileall -q app` и полный запуск `python run.py check`: `68 passed`.


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
- Интерфейс переработан как рабочее место оператора, а не техническая витрина данных:
  - сверху показывается только главное решение: `НЕТ ВХОДА`, `НАБЛЮДАТЬ` или `К ПРОВЕРКЕ`;
  - рядом выводится итоговая оценка допуска, но она не является приказом на сделку;
  - trade ticket показывает только то, что нужно для ручной проверки: symbol, direction, strategy, entry, SL, TP, R/R, confidence;
  - чек‑лист допуска отделяет hard stop-факторы от предупреждений;
  - доказательства стратегии, backtest, ML и sentiment вынесены в отдельный блок;
  - протокол оператора явно описывает, что нужно проверить руками до создания бота;
  - операции синхронизации и технические детали скрыты в раскрываемых секциях, чтобы не мешать торговому решению.

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
2. `Sync market` — загрузить свечи, funding и open interest по выбранным таймфреймам. Поле UI принимает `15,60,240`.
3. `Sync sentiment` — загрузить Fear&Greed/GDELT/RSS и рассчитать market_microstructure отдельно для каждого TF.
4. `Build signals` — построить rule-based сигналы вручную по одному или нескольким TF, если нужно немедленно.
5. Авто-контур `signal-auto-refresher` делает шаги 1–4 периодически сам, если включен `SIGNAL_AUTO_REFRESH_ENABLED=true`. По умолчанию он работает как MTF-контур `15m/1h/4h`.
6. `Backtest` — проверить стратегию на истории.
7. `Train ML` — обучить модель ранжирования.
8. `Rank candidates` — выбрать кандидатов для paper-trading.
9. `LLM brief` — получить риск-ориентированное объяснение сигнала.

## Ollama / LLM

```env
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b
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
GET  /api/signals/latest            # по умолчанию entry_only=true для 15m UI-очереди
GET  /api/signals/background/status
POST /api/signals/background/run-now
GET  /api/research/rank
POST /api/backtest/run
GET  /api/backtest/background/status
POST /api/backtest/background/run-now
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

Ожидаемый результат текущей ревизии: `47 passed`.

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
- ML-инференс в `app.ml.predict_latest` явно приводит feature-вектор к числовой матрице до `fillna(0.0)`, поэтому `FutureWarning` из `latest[FEATURE_COLUMNS].to_frame().T.fillna(0.0)` больше не возникает;
- отсутствие liquidity snapshot остается безопасным состоянием `False`, то есть сигнал не должен считаться ликвидным без доказательства.

Ожидаемый результат текущей ревизии:

```bash
python run.py check
python run.py test
```

Ожидаемый результат полного прогона после обновления: `47 passed`.

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

Ожидаемый результат полного прогона после обновления: `47 passed`.

### Усиленное исправление `joblib/loky` warning через `sitecustomize.py`

Если предупреждение `Could not find the number of physical cores ... wmic` появляется даже после установки `LOKY_MAX_CPU_COUNT`, это означает, что конкретная связка Windows/Python/joblib запускает проверку физических ядер раньше или независимо от обычной runtime-настройки.

В текущей ревизии добавлен корневой `sitecustomize.py`. Python загружает его автоматически при запуске из корня проекта, поэтому переменная `LOKY_MAX_CPU_COUNT` и точечный фильтр именно этого warning применяются до импорта `uvicorn`, `sklearn` и `joblib`.

После обновления полностью остановите старый сервер и запустите новый процесс из корня проекта:

```powershell
cd C:\AITrading\BybitResearchLabAI
python run.py
```

Если проект запускается из IDE, планировщика или службы Windows, проверьте, что рабочая папка процесса — корень проекта. Резервный вариант — задать переменную системно:

```powershell
setx LOKY_MAX_CPU_COUNT 4
```

После `setx` нужно открыть новый терминал и перезапустить сервер.

### Примечание по Windows и joblib/loky

На Windows без `wmic` joblib/loky может печатать warning при определении физических ядер. Проект автоматически задает безопасный `LOKY_MAX_CPU_COUNT`; при запуске через `python run.py` это значение дополнительно передается в дочерний процесс Uvicorn/reloader. Если сервер запускается напрямую, можно явно указать:

```powershell
$env:LOKY_MAX_CPU_COUNT="4"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### LLM brief и JSON-совместимость payload

Endpoint `POST /api/llm/brief` принимает пользовательский payload или строку из таблицы `signals`. Так как данные PostgreSQL/pandas могут содержать `datetime`, `Decimal`, numpy/pandas-типы и `pd.NA`, проект перед отправкой данных в LLM-промпт рекурсивно приводит payload к JSON-совместимому виду через `app.serialization.to_jsonable()`.

Это предотвращает `500 Internal Server Error` на `json.dumps(...)` и сохраняет поведение системы как research-рекомендателя: неизвестные объектные типы безопасно переводятся в строковое представление, а не используются для автоматического исполнения сделок.

## Интерфейс Decision Cockpit

Фронтенд переработан из технической таблицы в decision cockpit для ручного оператора. Главный экран теперь сначала показывает итоговый статус кандидата (`ПРОВЕРИТЬ`, `НАБЛЮДАТЬ`, `ЗАПРЕТ`), оценку, направление, план сделки, risk/reward, ограничения позиции, причины сигнала и стоп-факторы. Служебные таблицы universe/ranking/signals перенесены в раскрываемый блок технических деталей, чтобы не мешать принятию решения.

Важно: интерфейс не отправляет ордера и не создает ботов автоматически. Статус `ПРОВЕРИТЬ` означает только, что кандидата можно передать оператору на ручную проверку стакана, новостей, риска портфеля и актуальности цены.



## Фоновое автоматическое обновление рекомендаций

Главный разрыв прежней версии: интерфейс обновлял экран, backtest и LLM могли работать в фоне, но новые рыночные данные и новые рекомендации появлялись только после ручных кнопок `Загрузить рынок` и `Построить рекомендации`. Это создавало ложное ощущение автоматизма: LLM оценивал только уже существующие кандидаты, а не инициировал обновление сигналов.

Теперь при запуске FastAPI стартует отдельный сервис `signal-auto-refresher`:

```text
liquidity universe -> market sync по TF -> sentiment sync по TF -> build/persist signals по TF -> wake backtest + LLM
```

Поведение:

- сервис не отправляет ордера, не создает grid-ботов и не меняет биржевой аккаунт;
- universe берется из актуального liquidity-среза Bybit, затем ограничивается `SIGNAL_AUTO_MAX_SYMBOLS`;
- `SIGNAL_AUTO_INTERVALS` задает независимые Bybit-таймфреймы, по умолчанию `15,60,240` = 15m/1h/4h;
- свечи/funding/OI догружаются по каждому таймфрейму окном `SIGNAL_AUTO_SYNC_DAYS`;
- cold start по умолчанию грузит 30 дней, чтобы 1h/4h контуры имели запас больше минимальных 250 баров;
- сигналы строятся только по закрытым свечам и проходят `validate_signal()` перед сохранением;
- если появились новые/обновленные сигналы, автоматически будятся фоновый backtest и LLM-разбор;
- циклы защищены single-flight lock'ом, поэтому ручной `run-now` и плановый цикл не накладываются друг на друга;
- если liquidity/universe временно недоступны, сервис пробует последний сохраненный universe и только затем fallback на `DEFAULT_SYMBOLS`; при `REQUIRE_LIQUIDITY_FOR_SIGNALS=true` fallback-символы все равно не дадут рекомендаций без валидной ликвидности.

Параметры `.env`:

```env
SIGNAL_AUTO_REFRESH_ENABLED=true
SIGNAL_AUTO_REFRESH_INTERVAL_SEC=300
SIGNAL_AUTO_REFRESH_STARTUP_DELAY_SEC=20
SIGNAL_AUTO_MAX_SYMBOLS=25
SIGNAL_AUTO_SYNC_DAYS=30
SIGNAL_AUTO_INTERVALS=15,60,240
SIGNAL_AUTO_REFRESH_UNIVERSE=true
SIGNAL_AUTO_SYNC_SENTIMENT=true
```

Проверка и ручной внеочередной запуск:

```text
GET  /api/signals/background/status
POST /api/signals/background/run-now
```

Это именно автоматизация обновления рекомендательной витрины, а не автоматическая торговля. Оператор по-прежнему принимает решение вручную.

### Multi-timeframe логика и intraday consensus

MTF строится в два этапа. Сначала проект независимо сохраняет сигналы по каждому Bybit `interval`: у каждой строки свой `interval`, `bar_time`, backtest/LLM-статус и дедупликация. Затем слой `app/mtf.py` группирует свежие сигналы одного символа и рассчитывает intraday-consensus.

По умолчанию используется безопасная иерархия:

```text
15m  — entry trigger, единственный TF, который может быть кандидатом на вход;
60m  — directional bias, подтверждает или запрещает 15m-направление;
240m — старший regime/veto, запрещает вход против выраженного старшего режима.
```

Классы MTF:

```text
HIGH_CONVICTION_INTRADAY — 15m, 60m и 240m согласованы;
BIAS_ALIGNED_INTRADAY   — 15m подтвержден 60m, 240m нейтрален/без сигнала;
TACTICAL_ONLY           — есть только 15m без подтверждения 60m;
NO_TRADE_CONFLICT       — 60m или 240m против направления 15m;
CONTEXT_ONLY            — внутренний сигнал 60m/240m: используется в MTF-контексте, но не выводится в очередь рекомендаций как сделка.
```

`research_score` теперь пересчитывается с учетом `mtf_score`, `mtf_veto`, `higher_tf_conflict` и роли таймфрейма. Исходная оценка сохраняется в поле `research_score_base`. В очередь `/api/research/rank` и UI попадают только entry-кандидаты `15m`; `60m` и `240m` остаются внутри полей `mtf_bias` и `mtf_regime`. Для LLM в payload добавляются `mtf_status`, `mtf_action_class`, `mtf_entry`, `mtf_bias`, `mtf_regime` и причина решения, но LLM также оценивает только 15m entry-кандидатов.

Параметры `.env`:

```env
MTF_CONSENSUS_ENABLED=true
MTF_ENTRY_INTERVAL=15
MTF_BIAS_INTERVAL=60
MTF_REGIME_INTERVAL=240
```

Ручные endpoints `/api/sync/market`, `/api/sync/sentiment`, `/api/signals/build` принимают как старый параметр `interval`, так и новый `intervals`. UI отправляет оба поля для обратной совместимости. `/api/research/rank` умеет принимать `interval=15,60,240`, `interval=all`, `interval=multi` или один конкретный TF, но при включенном MTF-consensus возвращает торговые рекомендации только по `MTF_ENTRY_INTERVAL=15`; старшие TF используются только как контекст.


## Фоновый backtest актуальных рекомендаций

Backtest теперь работает не только по ручной кнопке. При запуске FastAPI стартует фоновый сервис `backtest-auto-runner`, который периодически ищет свежие рекомендации без актуального backtest по паре `category + interval + symbol + strategy` и пересчитывает их ограниченной очередью:

```text
latest signals -> stale/missing backtest filter -> sequential backtest -> PostgreSQL backtest_runs/backtest_trades -> research ranking/UI
```

Поведение:

- сервис не отправляет ордера и не меняет сами рекомендации;
- пересчитываются только свежие signal-кандидаты, у которых backtest отсутствует, старее сигнала или старее `BACKTEST_AUTO_TTL_HOURS`;
- тяжелая работа ограничена `BACKTEST_AUTO_MAX_CANDIDATES` за цикл и `BACKTEST_AUTO_LIMIT` свечами на один прогон;
- циклы защищены lock'ом: ручной `run-now` и плановый цикл не выполняются параллельно;
- после `POST /api/signals/build`, если появились новые сигналы, фоновый backtest будится автоматически;
- ручная кнопка `Авто-бэктест сейчас` только ставит запрос на ближайший фоновый цикл, а не блокирует UI тяжелым расчетом.

Параметры `.env`:

```env
BACKTEST_AUTO_ENABLED=true
BACKTEST_AUTO_INTERVAL_SEC=900
BACKTEST_AUTO_STARTUP_DELAY_SEC=45
BACKTEST_AUTO_MAX_CANDIDATES=8
BACKTEST_AUTO_LIMIT=5000
BACKTEST_AUTO_TTL_HOURS=24
```

Проверка состояния:

```text
GET /api/backtest/background/status
POST /api/backtest/background/run-now
POST /api/backtest/run        # ручной backtest выбранного сетапа оставлен для точечной проверки
```

Важно: это автоматизация исследовательской доказательной базы, а не автоматическое торговое исполнение. Backtest может быть устаревшим, если рыночные данные давно не обновлялись; сначала нужно синхронизировать свечи и построить свежие рекомендации.

## Фоновая LLM-оценка кандидатов

LLM-разбор больше не является обязательным ручным действием оператора. При запуске FastAPI стартует фоновый сервис `llm-auto-evaluator`:

```text
/api/research/rank -> top-кандидаты -> worker threads -> Ollama -> PostgreSQL llm_evaluations -> UI
```

Поведение:

- сервис периодически берет top-кандидатов из research ranking;
- оценивает их в отдельных worker-thread'ах;
- сохраняет результат в таблицу `llm_evaluations`;
- UI показывает готовый LLM-вердикт, статус `running/error/pending` и время обновления;
- ручная кнопка `Обновить LLM сейчас` не формирует brief синхронно, а только просит фоновый сервис выполнить ближайший цикл;
- сервис не отправляет ордера, не создает ботов и не меняет торговое состояние.

Параметры `.env`:

```env
LLM_AUTO_EVAL_ENABLED=true
LLM_AUTO_EVAL_INTERVAL_SEC=300
LLM_AUTO_EVAL_STARTUP_DELAY_SEC=15
LLM_AUTO_EVAL_MAX_CANDIDATES=8
LLM_AUTO_EVAL_WORKERS=2
LLM_AUTO_EVAL_TTL_MINUTES=60
```

Проверка состояния:

```text
GET /api/llm/background/status
GET /api/llm/evaluations/latest?limit=100
POST /api/llm/background/run-now
```

Что остается ручным намеренно: ML-train, финальная проверка сетапа оператором и любое биржевое исполнение. Обновление рынка, sentiment и построение новых рекомендаций теперь может выполняться фоновым `signal-auto-refresher`; ручные кнопки сохранены для внеочередной диагностики.

### Frontend redesign v3

Интерфейс рабочего места оператора переработан как dark-mode trading terminal:

- новая shell-компоновка: sidebar, topbar со статусами, левая колонка `KPI + Candidate queue + Data operations`, основная область `Primary decision + Trade sheet + MTF consensus`;
- главный вердикт и score визуально отделены от технических данных;
- очередь кандидатов стала компактной и клавиатурно доступной;
- операции с данными раскрыты по умолчанию, но ограничены собственной прокруткой;
- risk/evidence/LLM/news/protocol вынесены в support-блок, а сырые данные и журнал остаются в `<details>`;
- сохранены защиты UI: `AbortController` timeout, busy guard от повторных запусков, безопасные внешние ссылки `http/https`, нормализация CSS-классов из backend-данных.

### Frontend corrective pass v4

Дополнительно исправлена интерактивность operator cockpit:

- sidebar-кнопки больше не декоративные: рабочая область, график, protocol, операции, настройки и help выполняют действия;
- burger-кнопка сворачивает sidebar;
- ошибки и успехи операций показываются в видимом `operationToast`/`operationStatus`, а не только в скрытом журнале;
- busy-state блокирует только API-action кнопки с `data-busy-lock="true"`, поэтому вкладки, фильтры, help и навигация остаются доступными;
- добавлена клиентская валидация параметров перед API-запросами;
- палитра снижена по яркости до теплой muted-neutral схемы для длительной операторской работы.

### UI v5: операторский cockpit

Фронтенд пересобран в более спокойной dark-mode trading/fintech-стилистике. Основные изменения:

- компактная карточка первичного решения вместо чрезмерно большой плашки;
- полностью раскрытая и читаемая `Candidate Queue`;
- полноширинная раскрываемая панель `Операции с данными` с корректным `aria-expanded` и явной кнопкой сворачивания;
- отдельные рабочие карточки `Trade Sheet`, `MTF Consensus`, `Risk & Evidence`, `News & Sentiment`, `Protocol`;
- отдельное обновление очереди и сохранение busy-lock только для API-операций.

### UI v6: выравнивание рабочих панелей и чистая очередь

В последней версии frontend дополнительно исправлены два пользовательских дефекта:

- `Candidate Queue`, `Trade Sheet` и `MTF Consensus` имеют одинаковую высоту в основной рабочей строке; переполнение данных прокручивается внутри соответствующей панели.
- `Candidate Queue` дедуплицирует рекомендации по `symbol + interval`, оставляя лучший вариант рынка по приоритету решения, score, confidence, profit factor, drawdown и win rate. Если backend вернул несколько вариантов одного рынка, footer очереди показывает число скрытых дублей.

Проверка:

```text
node --check frontend/app.js — OK
direct frontend regression runner — OK, 10/10
python -S -m compileall -q app tests run.py install.py sitecustomize.py — OK
```
