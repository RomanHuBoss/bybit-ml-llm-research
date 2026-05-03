# Bybit Futures Advisory Research Lab

Советующая СППР для анализа крипторынка Bybit. Проект собирает публичные рыночные данные, строит технические/рыночные признаки, применяет стратегические правила, MTF-фильтрацию, backtest/ML/LLM evidence и показывает оператору решения в формате `НЕТ ВХОДА` / `НАБЛЮДАТЬ` / `ИССЛЕДОВАТЕЛЬСКИЙ КАНДИДАТ` / `РУЧНАЯ ПРОВЕРКА ВХОДА`.

> **Критичное ограничение:** система является советующей СППР и не должна автоматически отправлять ордера. В проекте используется публичный Bybit REST для market data; live order execution отсутствует намеренно. Любые entry/SL/TP значения являются аналитическими подсказками для ручной проверки оператором.

## Архитектура

```text
frontend/                 Vanilla JS/CSS/HTML trading cockpit
app/api.py                API-контракт и endpoint-функции
app/bybit_client.py       Bybit V5 public REST client, retry/backoff, ingestion
app/strategies.py         Правила сигналов, validation, persist latest signals
app/mtf.py                15m/60m/240m MTF consensus и veto
app/recommendation.py     Каноническое операторское решение и strategy-quality gate
app/strategy_quality.py    Квалификация стратегий APPROVED/WATCHLIST/RESEARCH/REJECTED
app/strategy_quality_background.py Фоновый bounded refresh Strategy Quality Gate без HTTP-timeout
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
STRATEGY_QUALITY_REFRESH_LIMIT=200
STRATEGY_QUALITY_REFRESH_TIME_BUDGET_SEC=30
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
5. вручную проверить entry, SL, TP, R/R, MTF, liquidity, LLM/backtest/ML evidence;
6. отличать торговые карточки `REVIEW_ENTRY` от исследовательских `RESEARCH_CANDIDATE`.

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
- фонового non-blocking Strategy Quality refresh без 45-секундного UI-timeout;
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
- `RESEARCH_CANDIDATE` / `ИССЛЕДОВАТЕЛЬСКИЙ КАНДИДАТ` — технический сетап есть, но стратегия еще не имеет статуса `APPROVED`;
- `REVIEW_ENTRY` / `РУЧНАЯ ПРОВЕРКА ВХОДА` — сетап можно вынести на ручную проверку только после strategy-quality gate, но это не приказ на сделку.

## Veto-логика

Hard-veto срабатывает при:

- stale/no-bar/unclosed данных;
- отсутствии торгового направления;
- MTF conflict/context-only;
- невалидном порядке SL/TP;
- слишком низком R/R;
- confidence ниже защитного минимума;
- отрицательном backtest при достаточном числе сделок;
- отсутствии статуса `APPROVED` у стратегии, если включен `REQUIRE_STRATEGY_APPROVAL_FOR_REVIEW`;
- spread выше лимита;
- liquidity universe пометил рынок как неeligible.

Дополнительные evidence-заметки ML/LLM/backtest могут снижать score или требовать ручной проверки, но отсутствие optional evidence само по себе не превращается в вечный hard-veto.

## MTF-логика

Роль таймфреймов задается настройками:

- entry TF: по умолчанию `15`;
- bias TF: по умолчанию `60`;
- regime TF: по умолчанию `240`.

Только entry-TF может быть торговым кандидатом. Bias/regime TF используются как контекст. Если старший TF явно конфликтует с entry-направлением, candidate получает hard-veto.

## Strategy Quality refresh и устранение UI-timeout

Ручная кнопка `Quality refresh` больше не выполняет тяжелый пересчет `strategy_quality` в HTTP-потоке. Endpoint `POST /api/strategies/quality/refresh` ставит bounded-задачу в фоновый сериализованный исполнитель и сразу возвращает статус. Текущее состояние доступно через `GET /api/strategies/quality/refresh/status`.

Синхронный режим сохранен только для CLI/малых диагностических прогонов: `POST /api/strategies/quality/refresh?wait=true&limit=10`. Любой refresh ограничен `STRATEGY_QUALITY_REFRESH_LIMIT` и soft-budget `STRATEGY_QUALITY_REFRESH_TIME_BUDGET_SEC`; при превышении бюджета возвращается `partial=true`, а UI показывает `refresh running/done/error/partial` вместо неинформативного `API timeout after 45s`.

## Recommendation API V32

Канонические endpoints для витрины оператора:

- `GET /api/recommendations/active` — активные серверно проверенные рекомендации с `entry`, `stop_loss`, `take_profit`, `risk_reward`, `confidence_score`, `expires_at`, объяснением и price-status.
- `GET /api/recommendations/{signal_id}` — полный контракт одной рекомендации.
- `GET /api/recommendations/{signal_id}/explanation` — краткое объяснение факторов за/против без UI-догадок.
- `GET /api/recommendations/{signal_id}/similar-history` — история завершённых похожих рекомендаций по тому же `symbol + interval + strategy + direction`, включая realized R, MFE/MAE, winrate, PF и предупреждение о малой выборке.
- `POST /api/recommendations/{signal_id}/operator-action` — аудит действий оператора: пропуск, ожидание подтверждения, ручной разбор, закрытие как неактуальной.

История похожих сигналов не используется как точная вероятность прибыли текущей сделки. Это отдельный evidence-слой, который показывает размер выборки и качество похожих завершённых рекомендаций.

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
- `strategy_matrix`: фоновая проверка матрицы `symbols × intervals × strategies` для предварительной квалификации стратегий.

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
- `Quality refresh` долго идет: это штатная фоновая операция; смотрите статус в Strategy Lab или `/api/strategies/quality/refresh/status`. Если часто видите `partial=true`, уменьшите `STRATEGY_QUALITY_REFRESH_LIMIT` или увеличьте `STRATEGY_QUALITY_REFRESH_TIME_BUDGET_SEC`.
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


## Ревизия V18 — symbol-scoped liquidity, Bybit pagination и UI resilience от 2026-04-29

Дополнительная жесткая проверка после замечаний экспертов закрыла несколько дефектов, которые могли приводить к неверной операторской оценке сделки:

- `/api/signals/latest` и `app/research.py` больше не используют глобальный `MAX(captured_at)` по всей категории. Последний liquidity snapshot выбирается отдельно по каждому `symbol`, иначе частичный sync одного инструмента мог сделать ликвидность остальных рынков неизвестной или неверной.
- `app/symbols.py` также переведен на per-symbol latest liquidity: dynamic universe больше не строится по единственному глобальному timestamp и не допускает stale-symbols в выборку.
- Введен параметр `LIQUIDITY_SNAPSHOT_MAX_AGE_MINUTES=120`. Устаревший snapshot не считается доказательством свежего spread/eligibility: в API он возвращается как `liquidity_status=stale`, а числовые liquidity-поля не используются для положительного решения.
- `app/features.py` больше не переносит старый spread/eligibility вперед через `ffill` без ограничения возраста. Это защищает veto и confidence от устаревшего стакана.
- `app/bybit_client.py` добавил cursor-pagination для `/v5/market/open-interest`, включая защиту от зацикленного cursor.
- `app/api.py` синхронизирован со всеми стратегиями: `trend_continuation_setup` теперь присутствует в публичном статусе стратегий.
- `frontend/app.js` отображает `fresh/stale/missing` состояние liquidity snapshot в operator checklist и не считает ошибку фоновой LLM-оценки фатальной ошибкой построения сигналов.
- Добавлены regression-тесты для stale/fresh liquidity, per-symbol liquidity SQL contract, Bybit open-interest pagination и frontend liquidity degradation.

Принятое допущение V18: если liquidity snapshot старше `LIQUIDITY_SNAPSHOT_MAX_AGE_MINUTES`, он может отображаться как техническая диагностическая информация, но не должен использоваться как подтверждение допустимости ручного входа. Оператор обязан проверить стакан/спред вручную либо дождаться свежего sync.

Проверки V18:

```bash
python -S -m py_compile app/config.py app/features.py app/api.py app/research.py app/bybit_client.py
node --check frontend/app.js
pytest -q --import-mode=importlib -p no:cacheprovider
```

В текущей среде полный pytest-прогон выполнен из активного Python runtime, потому что обычный shell-процесс Python в этой sandbox-сессии зависал на platform `sitecustomize`/scientific-stack teardown. Результат полного прогона: `119 passed`.

Отчет аудита V18 сохранен в `docs/RED_TEAM_AUDIT_2026-04-29_V18.md`.


## Ревизия V19 — strategy-quality gate и разделение research/review от 2026-04-30

Эта ревизия исправляет главный продуктовый дефект: слабый или малый бэктест больше не показывается как торговая рекомендация. Теперь такой сетап получает статус `RESEARCH_CANDIDATE`, а `REVIEW_ENTRY` разрешается только после прохождения strategy-quality gate.

Что изменено:

- Добавлен модуль `app/strategy_quality.py` и таблица `strategy_quality` в `sql/schema.sql`.
- Введены статусы качества стратегий: `APPROVED`, `WATCHLIST`, `RESEARCH`, `REJECTED`, `STALE`.
- `app/recommendation.py` больше не допускает `REVIEW_ENTRY` при отсутствующем, слабом или малом backtest evidence.
- `app/backtest.py` после каждого прогона обновляет качество стратегии.
- `app/backtest_background.py` переведен из режима проверки случайных свежих сигналов в режим `strategy_matrix`: `symbols × intervals × strategies`.
- `app/research.py` подтягивает `strategy_quality` и учитывает его в ранжировании.
- `app/api.py` добавил `/api/strategies/quality` и `/api/strategies/quality/refresh`, а `/api/status` отражает параметры gate.
- Frontend получил отдельный фильтр `RESEARCH`, отдельный визуальный статус `RESEARCH_CANDIDATE`, колонку `Quality` и пункт `strategy_quality` в checklist.
- `.env.example` синхронизирован с новыми параметрами qualification gate и более длинным backtest horizon.

Новый безопасный контракт:

```text
NO_TRADE            = вход запрещен hard-veto
WAIT                = наблюдать
RESEARCH_CANDIDATE  = сетап есть, но стратегия не approved
REVIEW_ENTRY        = только ручная проверка approved-сетапа
```

Проверки V19:

```bash
python -m py_compile app/config.py app/strategy_quality.py app/recommendation.py app/backtest.py app/backtest_background.py app/research.py app/api.py
pytest -q
```

Результат полного regression-прогона: `120 passed`.

Подробное описание сохранено в `docs/STRATEGY_QUALITY_GATE_2026-04-30.md`.

## Ревизия V20 — Strategy Lab, diagnostics и walk-forward evidence от 2026-04-30

Эта ревизия доводит V19 до продуктово пригодного состояния: теперь есть отдельный Strategy Lab для квалификации стратегий и диагностический блок, объясняющий, почему Trading Desk пуст или почему конкретный сетап не стал `REVIEW_ENTRY`.

Ключевые изменения:

- Добавлен `app/strategy_lab.py`.
- Добавлены endpoints `GET /api/strategies/lab` и `GET /api/trading-desk/diagnostics`.
- `strategy_quality` расширен метриками `expectancy`, `last_30d_return`, `last_90d_return`, `walk_forward_pass_rate`, `walk_forward_windows`, `walk_forward_summary`.
- `run_backtest` теперь сначала сохраняет сделки, затем пересчитывает quality, чтобы walk-forward/expectancy считались по реальным `backtest_trades`.
- Frontend получил отдельный блок `Strategy Lab`, воронку статусов и понятные blocker-коды.
- Добавлена кнопка `Quality refresh`.
- Если `REVIEW_ENTRY = 0`, UI показывает не пустоту, а диагностику причин.
- В `docs/QUALITY_SNAPSHOT_2026-04-30.json` сохранён контрольный пример quality-выгрузки.

Проверка:

```bash
python -S -m py_compile app/config.py app/strategy_quality.py app/strategy_lab.py app/recommendation.py app/backtest.py app/backtest_background.py app/research.py app/api.py
node --check frontend/app.js
pytest -q
```

### V20 database migration for existing installs

For an existing PostgreSQL database, run once after pulling V20:

```bash
python -m app.migrate_v20_strategy_lab
```

Equivalent direct SQL:

```bash
psql -h <host> -p <port> -U <user> -d <db> -f sql/migrations/20260430_v20_strategy_lab.sql
```

This migration is idempotent. It creates `backtest_trades`, extends `strategy_quality`, and adds the indexes required by Strategy Lab.

## Ревизия V21 — institutional decision cockpit и backtest persistence guard от 2026-04-30

Эта ревизия закрывает UI/UX-проблему главного операторского экрана и один инфраструктурный дефект backtest persistence path.

Ключевые изменения:

- Главная decision-zone переработана в сторону **decision-first trading cockpit**: цена, expected move, entry, stop-loss, take-profit, freshness, data status, veto и причина veto теперь собраны в одном компактном блоке `decisionTelemetry`.
- Добавлены JS-formatter/helper-функции для безопасного отображения price/volume/PnL/score/R/R и degraded-значений без ложных нулей.
- Исправлен frontend warning-state для LLM/background errors: `warning` заменен на используемый UI-тон `warn`.
- Убран дублирующий `refreshStatus()` после market sync.
- В `styles.css` добавлен V21 institutional cockpit layer: более строгая dark-mode сетка, плотные KPI, telemetry grid, hover/micro-interactions, table highlights, skeleton loading, адаптивность и `prefers-reduced-motion`.
- `run_backtest()` теперь не ломает уже рассчитанный результат на idempotent-проверке `backtest_trades`, если storage migration недоступна в тестовой/maintenance-среде. Такое состояние возвращается как `persistence_warnings`, а не скрывается.
- Добавлены regression-тесты для V21 UI-contract и non-fatal backtest storage migration failure.

Проверки V21:

```bash
python -S -c "import sys; sys.path.insert(0, '/opt/pyvenv/lib/python3.13/site-packages'); sys.path.insert(0,'.'); import pytest; raise SystemExit(pytest.main(['-q','tests','--maxfail=10']))"
node --check frontend/app.js
python -S -c "import sys, compileall; sys.path.insert(0, '/opt/pyvenv/lib/python3.13/site-packages'); sys.path.insert(0,'.'); ok = compileall.compile_dir('app', quiet=1) and compileall.compile_dir('tests', quiet=1); raise SystemExit(0 if ok else 1)"
```

Результат полного regression-прогона: `127 passed`.

Принятое допущение V21: backtest storage migration warning не является торговым evidence и не повышает статус стратегии. Он нужен только для прозрачной диагностики persistence layer. Для production/staging все равно требуется применить миграции к PostgreSQL и отдельно проверить запись `backtest_trades` на реальной БД.

Отчет аудита V21 сохранен в `docs/RED_TEAM_AUDIT_2026-04-30_V21.md`.

---

## V23 — production hardening СППР / trust gate 2026

Эта ревизия ужесточает логику допуска рекомендаций, потому что для советующей trading‑СППР отсутствие доказанной устойчивости должно считаться дефектом, а не косметическим предупреждением.

### Что изменено

- Исправлен runtime-DDL `strategy_quality`: в fresh PostgreSQL больше нет дублирующего объявления `diagnostics JSONB`, которое могло ломать первичную инициализацию Strategy Lab.
- Добавлен 2026 trust gate для `REVIEW_ENTRY`: сохраненный `APPROVED` больше не обходится автоматически, если evidence устарел или не содержит walk-forward подтверждения при `REQUIRE_WALK_FORWARD_FOR_APPROVAL=true`.
- `strategy_quality` теперь может возвращать статус `STALE`, если `last_backtest_at` старше `STRATEGY_QUALITY_MAX_AGE_DAYS`. Такой сетап блокируется как `NO_TRADE` до актуализации evidence.
- В `evaluate_strategy_quality()` добавлены дополнительные защитные параметры: `STRATEGY_MIN_EXPECTANCY` и `STRATEGY_MIN_RECENT_30D_RETURN`.
- Серверная рекомендация теперь дополнительно возвращает `operator_risk_score`, `operator_risk_grade` и `operator_trust_status`.
- Frontend показывает trust/risk в карточке сделки, чек-листе и raw-таблице. Это помогает понять, почему торговая панель пуста: система не «сломалась», а не нашла сетап, прошедший trust gate.

### Новые параметры `.env`

```env
REQUIRE_WALK_FORWARD_FOR_APPROVAL=true
STRATEGY_QUALITY_MAX_AGE_DAYS=14
STRATEGY_MIN_EXPECTANCY=0.0
STRATEGY_MIN_RECENT_30D_RETURN=-0.03
```

### Практический смысл

`REVIEW_ENTRY` теперь должен означать не просто «есть технический сигнал», а «нет hard veto, уровни валидны, MTF не конфликтует, ликвидность подтверждена, Strategy Lab свежий, walk-forward не слабый, score-гейт пройден». Если эти условия не выполнены, интерфейс обязан показывать `WAIT`, `RESEARCH_CANDIDATE` или `NO_TRADE`, а не создавать иллюзию торговой рекомендации.

### Проверки V23

Минимальный быстрый набор:

```bash
node --check frontend/app.js
python -m compileall -q app tests
python -m pytest -q tests/test_strategy_lab_v20.py tests/test_operator_recommendation.py tests/test_strategy_quality_schema.py
```

Если локальная среда содержит сторонние pytest-плагины, влияющие на запуск тестов, можно изолировать их:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_strategy_lab_v20.py tests/test_operator_recommendation.py tests/test_strategy_quality_schema.py
```

После обновления production/staging БД нужно выполнить/проверить миграции и затем запустить `Strategy Quality refresh`, чтобы старые строки `APPROVED` получили новую оценку по V23-gate.

### V24 hotfix: `/api/signals/build` timeout

Если UI показывал ошибку `Signals built. API timeout after 45s: /api/signals/build`, причина была не обязательно в падении backend. Ручной build сигналов для MTF-корзины может быть тяжелым DB/indicator-пересчетом, а UI раньше использовал общий 45-секундный timeout.

Исправлено:

- `/api/signals/build` обрабатывает `symbol × interval` jobs через ограниченный пул `SIGNAL_BUILD_WORKERS`;
- ответ API содержит `workers` и `jobs` для диагностики;
- frontend использует `signalBuildTimeoutMs()` вместо общего 45-секундного таймаута;
- оператор видит статус тяжелого MTF-пересчета.

Рекомендация для слабого локального ПК или медленной БД: оставить `SIGNAL_BUILD_WORKERS=1..2`; для более мощного стенда можно поднять до 4, но не выше без проверки нагрузки PostgreSQL.

## V25: исправление stuck-in-Research в `/api/signals/latest`

В этой ревизии устранен критичный серверный разрыв между Strategy Lab и операторской витриной:

- `/api/research/rank` уже ранжировал кандидатов с учетом `strategy_quality`, последних `backtest_runs`, `model_runs`, `liquidity_snapshots` и `llm_evaluations`;
- `/api/signals/latest`, который фактически питает рабочее место оператора, ранее брал только свежие строки из `signals` и поэтому не видел `quality_status=APPROVED`, `quality_score`, `trades_count`, `profit_factor`, `walk_forward_pass_rate` и другие evidence-поля;
- из-за этого `classify_operator_action()` безопасно считал такие строки `RESEARCH`/`NO_BACKTEST`, и система могла днями показывать максимум `RESEARCH_CANDIDATE`, даже если Strategy Lab уже содержал approved evidence.

Теперь `/api/signals/latest` синхронизирован с research-контуром: endpoint подтягивает последние backtest/quality/model/liquidity/LLM evidence, рассчитывает `research_score`, передает полный контракт в `annotate_recommendations()` и только после freshness/MTF/queue-stability показывает `REVIEW_ENTRY`. Если API снова не передаст `quality_status`/`quality_score`, frontend явно подсветит ошибку контракта Strategy Quality, а не замаскирует ее как обычный Research.

Принятое безопасное допущение: `REVIEW_ENTRY` разрешается только при свежем `APPROVED` evidence и прохождении hard-veto. Старые legacy-строки `APPROVED`, которые не имеют актуального walk-forward/backtest evidence, не форсируются в сделку автоматически; их нужно обновить через фоновый Strategy Quality refresh/backtest. Это может уменьшать число входных рекомендаций, но защищает от ложного допуска.

## V26: почему очередь могла оставаться только Research при наличии Approved в Strategy Lab

Скриншот production UI показал уже не потерю API-контракта, а вторую проблему в логике допуска: `Approved` в Strategy Lab считался по всем TF, включая 60m/240m контекст, а операторская очередь строится только по `MTF_ENTRY_INTERVAL=15`. Поэтому на экране могло быть `Approved 15`, но `Trading Desk 0`: approved-строки относились к контекстным TF или к стратегиям, которые не дали свежий 15m entry-сетап.

Также полный quality gate требовал `STRATEGY_APPROVAL_MIN_TRADES=40` для каждого `symbol+15m+strategy`. На живой корзине это оказалось слишком жестким для advisory-only СППР: сильный свежий сетап с 10-39 локальными сделками, нормальным PF/DD и без hard veto всегда оставался `RESEARCH_CANDIDATE`, хотя оператору нужен хотя бы ручной разбор входа.

Исправление V26:

- KPI Strategy Lab теперь показывает `Approved 15m/all`, чтобы не смешивать entry-допуск и контекстные 60m/240m approvals.
- Добавлен безопасный пилотный режим `ALLOW_PROVISIONAL_REVIEW_FOR_SAMPLE_ONLY=true`.
- Если fresh 15m-сетап прошел MTF/liquidity/spread/RR/confidence, не имеет hard veto, не является `REJECTED`/`STALE`, имеет минимум `PROVISIONAL_REVIEW_MIN_TRADES`, PF не ниже `PROVISIONAL_REVIEW_MIN_PROFIT_FACTOR`, DD не выше `PROVISIONAL_REVIEW_MAX_DRAWDOWN`, а WF не катастрофически слабый, backend может вернуть `REVIEW_ENTRY` с `operator_quality_mode=provisional` и label `ПИЛОТНАЯ ПРОВЕРКА ВХОДА`.
- Это не полноценный `APPROVED` и не автоматическая сделка. UI обязан подсветить `PROVISIONAL_REVIEW`, а оператор обязан проверить график, стакан, риск и причину малого sample size.

Новые настройки:

```env
ALLOW_PROVISIONAL_REVIEW_FOR_SAMPLE_ONLY=true
PROVISIONAL_REVIEW_MIN_TRADES=10
PROVISIONAL_REVIEW_MIN_PROFIT_FACTOR=1.05
PROVISIONAL_REVIEW_MAX_DRAWDOWN=0.30
PROVISIONAL_REVIEW_MIN_WALK_FORWARD_PASS_RATE=0.35
PROVISIONAL_REVIEW_MIN_SCORE=60
```

Если нужен максимально консервативный режим, установите `ALLOW_PROVISIONAL_REVIEW_FOR_SAMPLE_ONLY=false`: тогда `REVIEW_ENTRY` снова будет доступен только для полного `APPROVED`.

## V30: recommendation operator actions and fee-adjusted contract

This revision extends the advisory recommendation contract without adding live order execution.

New backend-owned fields are returned inside each recommendation:

- `position_sizing.risk_amount_usdt`;
- `position_sizing.position_notional_usdt`;
- `position_sizing.estimated_quantity`;
- `position_sizing.margin_at_max_leverage_usdt`;
- `fee_slippage_roundtrip_pct`;
- `net_risk_reward`.

The frontend displays these values directly and does not recalculate position sizing.

A new operator audit endpoint records what the user decided to do with a recommendation:

```text
POST /api/recommendations/{signal_id}/operator-action
```

Allowed actions: `skip`, `wait_confirmation`, `manual_review`, `close_invalidated`, `paper_opened`.
Closing a recommendation as invalidated also writes an `invalidated` row to `recommendation_outcomes`, so it is reflected in future quality statistics.

Apply the repeatable migration when updating an existing database:

```bash
psql -U bybit_lab_user -d bybit_lab -f sql/migrations/20260503_v30_recommendation_operator_actions_and_quality.sql
```

## V35 — active recommendation integrity

Текущий контракт рекомендаций: `recommendation_v35`.

Ключевое изменение V35: активная выдача больше не показывает directional-сигналы, которые уже завершены outcome-evaluator или закрыты оператором. `/api/recommendations/active` требует `expires_at > NOW()` и исключает terminal outcomes. Метрики `/api/recommendations/quality` считаются только по завершённым рекомендациям (`outcome_status <> 'open'`), поэтому `winrate`, `profit_factor`, `average R`, MFE/MAE и confidence buckets не искажаются открытыми строками.

Добавлены SQL-view:

- `v_active_recommendation_contract_v35` — активные directional-рекомендации без terminal outcome;
- `v_recommendation_quality_terminal_v35` — качество рекомендаций только по завершённым outcomes.

Проверка текущей ревизии:

```bash
python run.py check
node --check frontend/app.js
```

В sandbox-проверке: `196 passed`.
