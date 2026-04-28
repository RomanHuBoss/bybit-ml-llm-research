# Bybit ML/LLM Research Lab

Советующая СППР для анализа крипторынка Bybit. Проект собирает публичные рыночные данные, строит технические/рыночные признаки, применяет стратегические правила, MTF-фильтрацию, backtest/ML/LLM evidence и показывает оператору рекомендации в формате `НЕТ ВХОДА` / `НАБЛЮДАТЬ` / `РУЧНАЯ ПРОВЕРКА ВХОДА`.

> **Критичное ограничение:** система не является торговым ботом и не должна автоматически отправлять ордера. В проекте используется публичный Bybit REST для market data; live order execution отсутствует намеренно. Любые entry/SL/TP/TP значения являются аналитическими подсказками для ручной проверки оператором.

## Архитектура

```text
frontend/                 Vanilla JS/CSS/HTML trading cockpit
app/api.py                API-контракт и endpoint-функции
app/bybit_client.py       Bybit V5 public REST client, retry/backoff, ingestion
app/strategies.py         Правила сигналов, validation, persist latest signals
app/mtf.py                15m/60m/240m MTF consensus и veto
app/recommendation.py     Каноническое операторское решение
app/safety.py             Freshness, stale-bar filtering, R/R diagnostics
app/research.py           Ранжирование кандидатов с backtest/ML/liquidity/LLM joins
app/backtest.py           Локальный backtest стратегий
app/ml.py                 ML train/predict для evidence-слоя
app/llm*.py               LLM summary/evaluation через Ollama-compatible API
app/signal_background.py  Фоновый контур universe → market → sentiment → signals
app/backtest_background.py Фоновый backtest evidence
app/db.py                 PostgreSQL helpers с ленивым импортом драйвера
sql/schema.sql            PostgreSQL schema
tests/                    Unit/static/integration regression tests
docs/                     Отчеты аудита и эксплуатационные заметки
```

## Технологии

- Python 3.11+;
- FastAPI/Uvicorn;
- PostgreSQL;
- Bybit V5 public REST;
- pandas/numpy/sklearn/joblib для research/ML;
- Vanilla JavaScript, HTML, CSS;
- pytest для regression-набора.

## Данные и источники

- Свечи Bybit `kline` по выбранным категориям `linear` / `inverse` / `spot`.
- Funding и open interest для деривативных категорий.
- Liquidity snapshot через tickers/instruments.
- Sentiment через Fear & Greed, GDELT/RSS и рыночные микропризнаки, если включено.
- LLM evidence через локальный или совместимый Ollama endpoint.

## Конфигурация

Скопируйте `.env.example` в `.env` и настройте параметры PostgreSQL, Bybit public endpoint, universe, фоновых задач и risk controls.

Минимальные параметры:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=bybit_lab
POSTGRES_USER=bybit_lab_user
POSTGRES_PASSWORD=change_me
DEFAULT_CATEGORY=linear
DEFAULT_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT
DEFAULT_INTERVAL=60
SIGNAL_AUTO_INTERVALS=15,60,240
MTF_ENTRY_INTERVAL=15
MTF_BIAS_INTERVAL=60
MTF_REGIME_INTERVAL=240
REQUIRE_LIQUIDITY_FOR_SIGNALS=true
MAX_SIGNAL_AGE_HOURS=48
```

Секреты реальной торговли в проект не требуются. Если в будущем будет добавлен private API, его нужно выносить в отдельный модуль исполнения с kill-switch, idempotency, durable outbox, reconciliation и аудитом.

## Установка

```bash
python -m venv .venv
. .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Создайте БД и примените схему:

```bash
psql -U bybit_lab_user -d bybit_lab -f sql/schema.sql
```

## Запуск

```bash
python run.py app
```

Фронтенд доступен через приложение FastAPI и статические файлы `frontend/`.

Базовые операции через UI:

1. выбрать категорию, символы и MTF-контур;
2. обновить universe/market/sentiment;
3. построить рекомендации или запустить фоновый контур;
4. анализировать очередь кандидатов и главный операторский вердикт;
5. вручную проверить entry, SL, TP, R/R, MTF, liquidity, LLM/backtest/ML evidence.

## Тесты и проверки

```bash
python -m pytest -q tests
python run.py check
node --check frontend/app.js
```

В текущей ревизии добавлены regression-проверки для:

- строковых `mtf_veto` / `higher_tf_conflict` на API/JSON границе;
- безопасной обработки `is_eligible="false"` в генераторе стратегий;
- directional validity SL/TP относительно LONG/SHORT;
- сортируемой таблицы сырых сигналов во frontend;
- сохранения advisory-only frontend-контракта.

## Торговая логика

Сигналы строятся стратегиями из `app/strategies.py`. Каждая рекомендация обязана иметь:

- направление `long` или `short`;
- конечный `confidence`;
- положительные `entry`, `stop_loss`, `take_profit`, `ATR`;
- корректный порядок уровней:
  - LONG: `stop_loss < entry < take_profit`;
  - SHORT: `take_profit < entry < stop_loss`;
- свежую закрытую свечу;
- непротиворечивый MTF-контекст.

`app/recommendation.py` возвращает канонический операторский контракт:

- `NO_TRADE` / `НЕТ ВХОДА` — есть hard-veto, вход запрещен;
- `WAIT` / `НАБЛЮДАТЬ` — критического запрета нет, но доказательности недостаточно;
- `REVIEW_ENTRY` / `РУЧНАЯ ПРОВЕРКА ВХОДА` — сетап можно вынести на ручную проверку, но это не приказ на сделку.

## Veto-логика

Hard-veto срабатывает при:

- stale/no-bar/unclosed данных;
- отсутствии торгового направления;
- MTF conflict/context-only;
- невалидном порядке SL/TP;
- слишком низком R/R;
- confidence ниже защитного минимума;
- отрицательном backtest при достаточном числе сделок;
- spread выше лимита;
- liquidity universe пометил рынок как неeligible.

Дополнительные evidence-заметки ML/LLM/backtest могут снижать score или требовать ручной проверки, но отсутствие optional evidence само по себе не превращается в вечный hard-veto.

## MTF-логика

Роль таймфреймов задается настройками:

- entry TF: по умолчанию `15`;
- bias TF: по умолчанию `60`;
- regime TF: по умолчанию `240`.

Только entry-TF может быть торговым кандидатом. Bias/regime TF используются как контекст. Если старший TF явно конфликтует с entry-направлением, candidate получает hard-veto.

## Frontend

Интерфейс реализован как dark-mode trading cockpit:

- верхняя панель: Bybit, pair, timeframe, freshness, LIVE OFF, статусы API/background;
- левая панель: очередь 15m-кандидатов, фильтры, параметры market/universe/strategy;
- центр: главный вердикт, confidence/risk/evidence, execution map, entry/SL/TP/R/R;
- правая панель: MTF, LLM, risk evidence, новости, protocol/checklist;
- нижняя зона: sortable raw table, technical log, debug details.

UI реализует состояния loading, empty, error, stale data, API unavailable, veto, no signal, conflicting indicators. Таблица сигналов имеет sticky header, сортировку по ключевым колонкам и подсветку направления.

## Режимы

- `paper/research`: основной режим проекта; рекомендации и backtest без исполнения.
- `live market data`: допускается получение публичных данных Bybit, но без private orders.
- `backtest`: локальная проверка стратегий на исторических свечах.

Отдельного live execution режима в проекте нет.

## Принятые допущения

- Bybit market data может быть временно недоступна; при ошибке API система должна показывать degraded/error state, а не скрыто строить рекомендации.
- Если liquidity snapshot отсутствует и `REQUIRE_LIQUIDITY_FOR_SIGNALS=true`, вход должен требовать ручной проверки или блокироваться на уровне hard-veto downstream.
- Optional evidence ML/LLM/backtest не заменяет hard risk controls.
- Stale-сигнал определяется по `bar_time` рыночной свечи, а не только по времени пересчета `created_at`.

## Известные ограничения

- Нет WebSocket/account reconciliation, потому что реального исполнения нет.
- Нет private Bybit API, управления позициями и ордерами.
- LLM evidence зависит от локального Ollama-compatible endpoint и не является источником торгового приказа.
- ML evidence зависит от доступности истории и актуальности model_runs.
- Полная production-эксплуатация требует мониторинга PostgreSQL, API rate limits, alerting и резервного восстановления.

## Troubleshooting

- Пустая очередь: проверьте свежесть свечей, MTF entry interval, liquidity filters и `MAX_SIGNAL_AGE_HOURS`.
- Все кандидаты `НЕТ ВХОДА`: откройте checklist/reasons; чаще всего причина в stale данных, MTF conflict, низком R/R или liquidity/spread.
- Ошибка Bybit: уменьшите число symbols/intervals/days, проверьте rate limits и сеть.
- Ошибка PostgreSQL: проверьте `.env`, доступность БД и примененную `sql/schema.sql`.
- LLM unavailable: проверьте `OLLAMA_BASE_URL`, модель и timeout.

## Риск-дисклеймер

Крипторынок высокорисковый. Проект предназначен для исследовательской и операторской поддержки принятия решений. Любые рекомендации должны проверяться человеком; ответственность за сделки и капитал остается на операторе.
