# Bybit Futures Advisory Research Lab

Советующая СППР для анализа крипторынка Bybit. Проект собирает публичные рыночные данные, строит технические/рыночные признаки, применяет стратегические правила, MTF-фильтрацию, backtest/ML/LLM evidence и показывает оператору рекомендации в формате `НЕТ ВХОДА` / `НАБЛЮДАТЬ` / `РУЧНАЯ ПРОВЕРКА ВХОДА`.

> **Критичное ограничение:** система является советующей СППР и не должна автоматически отправлять ордера. В проекте используется публичный Bybit REST для market data; live order execution отсутствует намеренно. Любые entry/SL/TP значения являются аналитическими подсказками для ручной проверки оператором.

## Архитектура

```text
frontend/                 Vanilla JS/CSS/HTML trading cockpit
app/api.py                API-контракт и endpoint-функции
app/bybit_client.py       Bybit V5 public REST client, retry/backoff, ingestion
app/strategies.py         Правила сигналов, validation, persist latest signals
app/mtf.py                15m/60m/240m MTF consensus и veto
app/recommendation.py     Каноническое операторское решение
app/operator_queue.py      Стабилизация очереди: 1 рынок = 1 операторский вердикт
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
- стабилизации operator queue и блокировки близкого LONG/SHORT-конфликта;
- безопасной обработки `is_eligible="false"` и отсутствующего liquidity snapshot в генераторе стратегий;
- практичного фьючерсного `trend_continuation_setup` с entry/SL/TP без автоматической торговли;
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

`app/recommendation.py` возвращает канонический операторский контракт, а `app/operator_queue.py` дополнительно стабилизирует выдачу: по одному symbol/TF в очередь попадает максимум один операторский вердикт. Если на одной свежей свече есть близкие по силе LONG и SHORT, рынок переводится в `КОНФЛИКТ СИГНАЛОВ` / `NO_TRADE`, чтобы оператор не видел хаотично сменяющиеся рекомендации.

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

Очередь слева намеренно показывает уникальные рынки, а не все технические стратегии подряд. Дубли стратегий агрегируются; если направления конфликтуют, карточка получает явный красный/желтый статус вместо смены одной рекомендации другой.

UI реализует состояния loading, empty, error, stale data, API unavailable, veto, no signal, conflicting indicators. Таблица сигналов имеет sticky header, сортировку по ключевым колонкам и подсветку направления.

## Режимы

- `paper/research`: основной режим проекта; рекомендации и backtest без исполнения.
- `live market data`: допускается получение публичных данных Bybit, но без private orders.
- `backtest`: локальная проверка стратегий на исторических свечах.

Отдельного live execution режима в проекте нет.

## Принятые допущения

- Bybit market data может быть временно недоступна; при ошибке API система должна показывать degraded/error state, а не скрыто строить рекомендации.
- Если liquidity snapshot отсутствует и `REQUIRE_LIQUIDITY_FOR_SIGNALS=true`, генератор теперь не должен молча глушить все рынки: он может создать candidate с entry/SL/TP и явным предупреждением `liquidity_unknown`; известная плохая ликвидность по-прежнему блокирует вход.
- Optional evidence ML/LLM/backtest не заменяет hard risk controls.
- Stale-сигнал определяется по `bar_time` рыночной свечи, а не только по времени пересчета `created_at`.
- Для спорного рынка безопаснее показать `NO_TRADE` с причиной конфликта, чем выбирать между LONG/SHORT по случайному порядку обновления evidence.

## Известные ограничения

- Нет WebSocket/account reconciliation, потому что реального исполнения нет.
- Нет private Bybit API, управления позициями и ордерами.
- LLM evidence зависит от локального Ollama-compatible endpoint и не является источником торгового приказа.
- ML evidence зависит от доступности истории и актуальности model_runs.
- Полная production-эксплуатация требует мониторинга PostgreSQL, API rate limits, alerting и резервного восстановления.

## Troubleshooting

- Пустая очередь: проверьте свежесть свечей, MTF entry interval, liquidity filters, `MAX_SIGNAL_AGE_HOURS` и наличие хотя бы одного сетапа после `trend_continuation_setup`.
- Все кандидаты `НЕТ ВХОДА`: откройте checklist/reasons; чаще всего причина в stale данных, MTF conflict, низком R/R или liquidity/spread.
- Ошибка Bybit: уменьшите число symbols/intervals/days, проверьте rate limits и сеть.
- Ошибка PostgreSQL: проверьте `.env`, доступность БД и примененную `sql/schema.sql`.
- LLM unavailable: проверьте `OLLAMA_BASE_URL`, модель и timeout.

## Риск-дисклеймер

Крипторынок высокорисковый. Проект предназначен для исследовательской и операторской поддержки принятия решений. Любые рекомендации должны проверяться человеком; ответственность за сделки и капитал остается на операторе.

## Ревизия V15 — red-team safety hardening от 2026-04-29

Дополнительная инженерная проверка подтвердила, что проект остается **advisory-only**: он не содержит private Bybit API, не подписывает запросы и не отправляет ордера. Основные усиления V15:

- `/api/signals/latest` теперь подтягивает последний liquidity snapshot (`liquidity_score`, `spread_pct`, `turnover_24h`, `open_interest_value`, `is_eligible`) до серверной классификации операторского решения. Без этого API мог вернуть `REVIEW_ENTRY` по сигналу, где UI видел ликвидность только через отдельный research/rank join.
- Unknown liquidity больше не считается достаточной для `REVIEW_ENTRY`, если включен `REQUIRE_LIQUIDITY_FOR_SIGNALS=true`. Такой сетап может попасть только в наблюдение/ручной разбор, пока не появится свежий snapshot.
- Явный `is_eligible=false` больше не трактуется как отсутствие snapshot. Это hard filter на уровне генерации стратегии и на уровне операторской рекомендации.
- Frontend перестал показывать абсолютный Risk/Reward для уровней, перепутанных относительно LONG/SHORT. Для LONG требуется `stop_loss < entry < take_profit`; для SHORT требуется `take_profit < entry < stop_loss`.
- `.env.example` синхронизирован с безопасными дефолтами ML-auto-train в `app/config.py`: `ML_AUTO_TRAIN_HORIZON_BARS=12`, `ML_AUTO_TRAIN_MAX_MODELS_PER_CYCLE=2`, `ML_AUTO_TRAIN_FAILURE_COOLDOWN_HOURS=6`.

Принятое допущение: при полностью отсутствующем liquidity snapshot стратегия может рассчитать кандидатный сетап, чтобы оператор видел рынок и причину неопределенности, но серверная рекомендация не переводит его в `REVIEW_ENTRY` до подтверждения ликвидности. Это безопаснее, чем молча скрывать рынок или, наоборот, разрешать вход без проверки стакана.

Дополнительные проверки V15:

```bash
node --check frontend/app.js
python -S -m py_compile app/*.py run.py install.py sitecustomize.py
python -S -m pytest -q tests/test_red_team_advisory_safety_v15.py
```

В отдельных Linux sandbox-сессиях Python с тяжелыми scientific-зависимостями (`pandas`/BLAS) может зависать при завершении процесса. Это не связано с логикой проекта; при таком симптоме запускайте тесты в чистом virtualenv из `requirements.txt` либо с ограничением потоков BLAS, как описано в `sitecustomize.py`.

## Ревизия V16 — жесткая инженерная верификация от 2026-04-29

Эта ревизия закрывает дополнительные дефекты, обнаруженные при повторном red-team аудите торгово-советующего контура:

- Feature-layer теперь явно маркирует отсутствие liquidity snapshot через `liquidity_state=unknown`. Это отделяет неизвестность от доказанного `is_eligible=false`.
- Strategy-layer трактует `liquidity_state=unknown` как warning-candidate: сетап можно рассчитать для очереди и объяснимости, но серверная рекомендация остается `WAIT`, пока ликвидность и spread не подтверждены.
- Явный `is_eligible=false` без `liquidity_state=unknown` остается hard filter и блокирует генерацию торгового сигнала.
- Исправлена обработка нулевых торговых признаков. Валидные значения `0.0` больше не подменяются дефолтами через `or default`; это критично для `bb_position=0.0`, `funding_rate=0.0`, `volume_z=0.0`, `ema20_50_gap=0.0`.
- Frontend risk meter больше не считает отсутствующий `spread_pct` нулевым риском. Unknown spread получает отдельный warning-вес.
- Добавлен static safety-test, подтверждающий отсутствие private Bybit order-execution markers в backend/frontend.
- Полный тестовый контур после правок: `109 passed`.

Дополнительное принятое допущение V16: если источник фичей не получил liquidity snapshot, он обязан передать это явно как `liquidity_state=unknown`. Placeholder-значения `spread_pct=999`, `liquidity_score=0` сами по себе больше не являются достаточным доказательством unknown-состояния, если одновременно присутствует явный `is_eligible=false` без маркера неизвестности.

Отчет аудита сохранен в `docs/RED_TEAM_AUDIT_2026-04-29.md`.

## Ревизия V17 — market-data/backtest/UI consistency hardening от 2026-04-29

Повторный аудит после V16 выявил дополнительные дефекты, влияющие на доказуемость рекомендаций и устойчивость интерфейса:

- Добавлен единый модуль `app/market_data_quality.py` для строгой проверки OHLCV-свечей до записи в БД и до расчета индикаторов. Невалидные `open/high/low/close`, `NaN`-объемы, отрицательные объемы/turnover, `high < low`, `high` ниже тела свечи и `low` выше тела свечи отбрасываются.
- `app/bybit_client.py` больше не пишет в `candles` незакрытые, malformed или физически невозможные Bybit kline-строки. Это защищает ATR, entry, stop-loss, take-profit, R/R и confidence от искажения одной битой свечой.
- `app/features.py` очищает market frame перед `add_indicators()`, поэтому ручные импорты или ранее поврежденные строки БД не попадают в индикаторы, ML/features и рекомендации.
- `app/backtest.py` теперь валидирует каждый торговый сигнал через тот же `validate_signal()`, что и live/advisory path. Бэктест больше не может открыть симулированную сделку по уровню, который боевой контур рекомендаций отверг бы как невалидный.
- `app/recommendation.py` различает отсутствие backtest evidence и бэктест без убыточных сделок. `profit_factor=None` при `trades > 0` и `win_rate=100%` больше не маркируется как `backtest_missing`; оператор видит отдельное предупреждение `backtest_no_losses` о необходимости проверить размер выборки.
- `frontend/app.js` стал устойчивее к отсутствующим DOM-узлам: обработчики кнопок и canvas-график теперь привязываются безопасно. Это снижает риск полного падения cockpit при частично измененной HTML-разметке.
- Выбор кандидата во frontend больше не зависит только от числового `id`. Для строк rank/fallback без `id` используется стабильный ключ `symbol|interval`, поэтому operator queue не теряет выбранный рынок при обновлении данных.

Дополнительные проверки V17:

```bash
python -S -m py_compile app/*.py run.py install.py sitecustomize.py
node --check frontend/app.js
pytest -q tests
```

В текущей sandbox-среде `pytest` один раз сообщил `113 passed`, но последующие процессы Python/pytest начали зависать на уровне импорта/завершения интерпретатора, что выглядит как ограничение окружения, а не как ошибка проекта. Поэтому для V17 дополнительно выполнены targeted/manual проверки нового модуля market-data quality и compile/static-проверки. Перед production/staging нужно повторить полный `pytest -q tests` в чистом virtualenv.
