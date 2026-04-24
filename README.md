# Bybit ML/LLM Research Lab

Локальная исследовательская система для Bybit: сбор рыночных данных, автоотбор ликвидных пар, расчёт признаков, бэктестинг стратегий, ML-ранжирование сетапов, бесплатный sentiment pipeline, LLM-резюме и paper-research.

Проект рассчитан на Windows 11 x64, PostgreSQL, Python и фронтенд на Vanilla JS/CSS/HTML. Docker не используется.

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
  scripts/
    setup_windows.ps1
    run_windows.ps1
    init_db.ps1
  docs/
    SENTIMENT.md
    STRATEGIES.md
    WINDOWS_SETUP.md
  tests/
    smoke_test.py
```

## Быстрый старт на Windows 11 x64

### 1. PostgreSQL

```sql
CREATE DATABASE bybit_lab;
CREATE USER bybit_lab_user WITH PASSWORD 'change_me';
GRANT ALL PRIVILEGES ON DATABASE bybit_lab TO bybit_lab_user;
GRANT ALL ON SCHEMA public TO bybit_lab_user;
ALTER SCHEMA public OWNER TO bybit_lab_user;
```

### 2. `.env`

```powershell
copy .env.example .env
notepad .env
```

### 3. Установка зависимостей

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

### 4. Инициализация БД

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\init_db.ps1
```

### 5. Запуск

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_windows.ps1
```

Открыть:

```text
http://127.0.0.1:8000
```

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
