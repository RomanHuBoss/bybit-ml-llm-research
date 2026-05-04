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

## Recommendation API V38

Канонические endpoints для витрины оператора:

- `GET /api/recommendations/active` — активные серверно проверенные рекомендации с `entry`, `stop_loss`, `take_profit`, `risk_reward`, `confidence_score`, `expires_at`, объяснением и price-status.
- `GET /api/recommendations/{signal_id}` — полный контракт одной рекомендации.
- `GET /api/recommendations/{signal_id}/explanation` — краткое объяснение факторов за/против без UI-догадок.
- `GET /api/recommendations/{signal_id}/similar-history` — история завершённых похожих рекомендаций по тому же `symbol + interval + strategy + direction`, включая realized R, MFE/MAE, winrate, PF и предупреждение о малой выборке.
- `POST /api/recommendations/{signal_id}/operator-action` — аудит действий оператора: пропуск, ожидание подтверждения, ручной разбор, закрытие как неактуальной.

История похожих сигналов не используется как точная вероятность прибыли текущей сделки. Это отдельный evidence-слой, который показывает размер выборки и качество похожих завершённых рекомендаций.


### Recommendation API V38 additions

- `contract_version = recommendation_v38`.
- `contract_health` в каждой рекомендации показывает, прошёл ли outbound-контракт серверные guardrails.
- `price_actionability.is_price_actionable=true` возможен только в `entry_zone`; состояние `extended` означает ждать ретест, а не догонять цену.
- `net_risk_reward` после fee/slippage участвует в review gate; слабый net R/R переводит сетап в hard/warn guardrail.
- Контракт содержит `decision_source=server_enriched_contract_v38` и `frontend_may_recalculate=false`; фронт больше не пересчитывает R/R и не повышает raw-сигнал до рекомендации.
- `GET /api/system/warnings` использует `v_recommendation_integrity_audit_v38`, если миграция применена. V38 дополнительно ловит чрезмерный TTL, конфликт активных LONG/SHORT по одному рынку/бару, слабый R/R, отсутствие объяснительного payload и отсутствие MTF-контекста.

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
