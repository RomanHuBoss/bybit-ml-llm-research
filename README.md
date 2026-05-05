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
docs/                     Отчеты аудита и эксплуатационные заметки, включая V46/V52 actionability и risk-disclosure audit
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

Создайте БД и примените схему с миграциями:

```bash
# Для новой пустой БД: применит sql/schema.sql, затем все sql/migrations/*.sql.
python run.py migrate --init-schema

# Для уже инициализированной БД: применит только еще не примененные миграции.
python run.py migrate
```

Скрипт ведет журнал примененных файлов в `public.schema_migrations`, проверяет SHA-256
каждой миграции и берет PostgreSQL advisory lock, чтобы два процесса не накатывали
изменения одновременно. Повторный запуск безопасен: уже примененные миграции будут
пропущены.

Полезные режимы:

```bash
python run.py migrate --list
python run.py migrate --dry-run
python run.py migrate --target 20260504_v43_recent_loss_quarantine.sql

# Альтернативные прямые запускатели:
python scripts/apply_migrations.py --init-schema
scripts/apply_migrations.sh --init-schema
# Windows PowerShell:
# .\scripts\apply_migrations.ps1 --init-schema
```

`python run.py init-db` оставлен только как legacy-команда для прямого применения
`sql/schema.sql`; для обычной эксплуатации используйте `python run.py migrate`.

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


## V49: операторский frontend-cockpit

Фронтенд переработан как единое рабочее место оператора, а не набор дублирующих плиток:

- слева: очередь 15m-рекомендаций, фильтры, параметры рынка и Strategy Lab;
- в центре: одно каноническое решение, execution map/equity и подробный trade sheet;
- справа: Risk & evidence, факторы решения, LLM, новости/sentiment, протокол, MTF и quality-сегменты;
- техническая таблица сырых сигналов и журнал операций спрятаны в раскрываемый блок `Технические детали и журнал`;
- карточки очереди больше не повторяют entry/SL/TP, а показывают только направление, статус, score, R/R, confidence и TTL;
- добавлено действие `Отметить paper-вход`, которое фиксирует операторское действие, но не отправляет ордер.

Каноническая торговая математика остается на backend: frontend только отображает `recommendation` contract и не пересчитывает `entry`, `stop_loss`, `take_profit`, `risk/reward` или `price_actionability`.

## Тесты и проверки

```bash
python -m pytest -q tests
python run.py check
node --check frontend/app.js
python -m compileall -q app
```

В текущей ревизии добавлены regression-проверки для:

- консервативного исполнения `SL-first`, если внутри одной OHLC-свечи одновременно достижимы SL и TP;
- явной маркировки `stop_loss_same_bar_ambiguous` в backtest, outcome evaluation, strategy-quality diagnostics, API-контракте и UI;
- запрета на `APPROVED` для стратегий, где высокая доля сделок зависит от неоднозначного внутрисвечного порядка;
- строковых `mtf_veto` / `higher_tf_conflict` на API/JSON границе;
- стабилизации operator queue и блокировки близкого LONG/SHORT-конфликта;
- безопасной обработки `is_eligible="false"` и отсутствующего liquidity snapshot в генераторе стратегий;
- практичного фьючерсного `trend_continuation_setup` с entry/SL/TP без автоматической торговли;
- directional validity SL/TP относительно LONG/SHORT;
- сортируемой таблицы сырых сигналов во frontend;
- фонового non-blocking Strategy Quality refresh без 45-секундного UI-timeout;
- сохранения advisory-only frontend-контракта;
- V44-защиты outcome evaluation от невалидных OHLC-свечей: плохие бары пропускаются, а результат получает `data_quality_issue`;
- V44-сегментов качества рекомендаций по `symbol`, `strategy`, `confidence bucket`, `timeframe`, `direction` и `signal_type`;
- V44-frontend панели качества похожих сигналов без сырых JSON и без пересчета торговой логики на клиенте;
- V44-миграции целостности market data/liquidity/outcome metrics;
- V45-расширения outbound-контракта: вложенный объект `recommendation` теперь самодостаточно содержит `entry`, `stop_loss`, `take_profit`, а системный аудит ловит неполный signal payload;
- V46 server actionability: `REVIEW_ENTRY`/`RESEARCH_CANDIDATE` демотируются в `missed_entry`/`wait`, если цена не в `entry_zone` или текущая цена неизвестна.
- V49 operator cockpit: DOM без дублирующихся id, единичный trade-ticket, скрытый legacy market-context mirror, компактная очередь без повторного вывода entry/SL/TP и paper-action без автоматической торговли.
- V51 operator action gate: `paper_opened` повторно проверяется backend и БД; unsafe paper-входы по blocked/missed/stale контрактам отклоняются сервером.
- V52 operator risk disclosure: каждый server-owned recommendation contract содержит `operator_risk_disclosures`; frontend показывает дисклеймеры рядом с trade ticket, а legacy `paper_trades` защищены CHECK-ограничениями LONG/SHORT/flat и audit-view `v_recommendation_integrity_audit_v52`.
- V53 market-context guardrails: directional-рекомендация получает серверный блок `market_context_guardrails` по volatility/risk distance/spread/liquidity/OI/funding/volume; hard-veto демотирует REVIEW_ENTRY в `blocked/no_trade`, frontend показывает отдельную карточку рыночного контекста, а SQL-аудит `v_recommendation_market_context_audit_v53` ловит non-finite numeric, out-of-range confidence и экстремальный ATR/risk distance.

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

## Модель исполнения SL/TP в backtest и outcome evaluation

OHLC-свеча не содержит точного внутрисвечного порядка цены. Поэтому если в одной свече одновременно достижимы `stop_loss` и `take_profit`, проект использует безопасную консервативную модель:

- `intrabar_execution_model = conservative_ohlc_stop_loss_first`;
- результат сделки засчитывается как `hit_stop_loss`;
- причина выхода маркируется как `stop_loss_same_bar_ambiguous`;
- в outcome notes выставляются `same_bar_stop_first=true`, `ambiguous_exit=true`, `both_sl_tp_touched=true`;
- backtest считает `ambiguous_exit_count`, `ambiguous_exit_rate` и `exit_reason_counts`;
- `strategy_quality` снижает оценку стратегии и не допускает `APPROVED`, если доля таких сделок превышает безопасный порог;
- frontend показывает отдельное предупреждение `SL-first`, чтобы оператор понимал, что статистика зависит от разрешения OHLC-неоднозначности.

Это намеренно более строгая модель, чем optimistic TP-first. Для повышения доверия к стратегии требуется проверка на меньшем таймфрейме или tick/trade данных.

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

## Recommendation API V40/V43/V44/V45/V46/V51/V52/V53

Канонические endpoints для витрины оператора:

- `GET /api/recommendations/active` — активные серверно проверенные рекомендации с `entry`, `stop_loss`, `take_profit`, `risk_reward`, `confidence_score`, `expires_at`, объяснением и price-status.
- `GET /api/recommendations/{signal_id}` — полный контракт одной рекомендации.
- `GET /api/recommendations/{signal_id}/explanation` — краткое объяснение факторов за/против без UI-догадок.
- `GET /api/recommendations/{signal_id}/similar-history` — история завершённых похожих рекомендаций по тому же `symbol + interval + strategy + direction`, включая realized R, MFE/MAE, winrate, PF и предупреждение о малой выборке.
- `POST /api/recommendations/{signal_id}/operator-action` — аудит действий оператора: пропуск, ожидание подтверждения, ручной разбор, закрытие как неактуальной.

История похожих сигналов не используется как точная вероятность прибыли текущей сделки. Это отдельный evidence-слой, который показывает размер выборки и качество похожих завершённых рекомендаций.


### Recommendation API V40/V43/V44/V45/V46/V51/V52/V53/V47/V48 additions

- `contract_version = recommendation_v40`.
- `contract_health` в каждой рекомендации показывает, прошёл ли outbound-контракт серверные guardrails.
- `price_actionability.is_price_actionable=true` возможен только в `entry_zone`; состояние `extended` означает ждать ретест, а не догонять цену.
- `net_risk_reward` после fee/slippage участвует в review gate; слабый net R/R переводит сетап в hard/warn guardrail.
- Контракт содержит `decision_source=server_enriched_contract_v40` и `frontend_may_recalculate=false`; фронт больше не пересчитывает R/R и не повышает raw-сигнал до рекомендации.
- `GET /api/system/warnings` сначала пробует `v_recommendation_market_context_audit_v53`/`v_recommendation_integrity_audit_v52`/`v_recommendation_integrity_audit_v48`/`v_recommendation_integrity_audit_v47`, затем fallback на `v_recommendation_integrity_audit_v46` с fallback на `v_recommendation_integrity_audit_v45`/`v_recommendation_integrity_audit_v44`/`v_recommendation_integrity_audit_v43`/`v_recommendation_integrity_audit_v40`, если новая миграция еще не применена. V40 ловит чрезмерный TTL, конфликт активных LONG/SHORT по одному рынку/бару, слабый R/R, отсутствие объяснительного payload и отсутствие MTF-контекста; V43 дополнительно ловит недавнюю серию убыточных рекомендаций по тому же symbol/TF/strategy/direction; V44 добавляет аудит невалидных OHLC/liquidity/outcome-метрик и сегментное качество рекомендаций; V45 добавляет аудит неполного structured signal payload; V46 добавляет аудит активной цены вне entry-zone и runtime-demotion небезопасного directional review; V47 публикует server-owned checklist; V48 добавляет freshness-guard для reference price.




## Market Context Guardrails V53

V53 добавляет отдельный серверный слой проверки рыночного контекста. Он не заменяет стратегию и не даёт разрешение на автоматическую сделку; его задача — не позволить формально валидному `entry/SL/TP` выглядеть пригодным для ручного входа, если текущий рынок делает сетап непрактичным.

Что проверяется в `app/trade_contract.py`:

- ATR/entry и ширина стопа как практическая волатильность и distance-to-stop;
- spread относительно `MAX_SPREAD_PCT`;
- `turnover_24h` и `open_interest_value` относительно liquidity-настроек;
- funding rate для `linear`/`inverse` рынков, включая direction-specific veto;
- volume z-score как подтверждение/аномалия объёма;
- отсутствие `NaN`/`Infinity` в критичных числах до API/UI.

Если market-context даёт hard-veto, backend демотирует `REVIEW_ENTRY`/`RESEARCH_CANDIDATE` в `blocked`, скрывает направление как `trade_direction=no_trade`, добавляет `market_context_blocks_entry` в `operator_risk_disclosures` и публикует причины в `factors_against`, `operator_checklist`, `signal_breakdown.market_context` и `recommendation.market_context_guardrails`.

Frontend показывает этот блок как отдельную карточку `Рыночный контекст` и как компактную метрику в trade ticket. Браузер не рассчитывает veto сам: он только отображает серверный контракт.

PostgreSQL-миграция `sql/migrations/20260505_v53_market_context_guardrails.sql` добавляет `ck_signals_no_numeric_infinity_v53`, индекс `idx_signals_market_context_audit_v53` и view `v_recommendation_market_context_audit_v53` для аудита confidence, non-finite чисел, отсутствующего market timestamp, истекшего TTL, неверных уровней и экстремального ATR/risk distance.

Принятое допущение V53: отсутствие optional funding/OI/volume snapshot создаёт `warn`, но само по себе не блокирует уже валидный `REVIEW_ENTRY`; известный плохой spread, экстремальная волатильность, слишком широкий стоп или direction-specific funding veto блокируют вход.

## Market Data Integrity and Quality Segments V44

V44 добавляет защитный слой вокруг качества исходных рыночных данных и интерпретации истории рекомендаций. Цель — не допустить, чтобы невалидная свеча, поврежденный liquidity snapshot или малая историческая выборка выглядели как полноценное подтверждение торгового решения.

Что изменено:

- `app/recommendation_outcomes.py` перед расчетом MFE/MAE/SL/TP проверяет OHLC-свечи на положительные конечные значения, `high >= low` и соответствие `open/close` диапазону свечи. Невалидные бары не участвуют в outcome calculation и маркируются в `notes` как `invalid_candles_skipped`; если валидных баров нет, outcome получает явную причину `no_valid_market_bars`.
- `/api/recommendations/quality` теперь возвращает не только общий quality snapshot, но и сегменты `by_symbol`, `by_strategy`, `by_confidence_bucket`, `by_timeframe`, `by_direction`, `by_signal_type`. Для каждого сегмента добавлены `sample_confidence` и человекочитаемый `sample_warning`, чтобы оператор видел отличие между качеством стратегии, качеством конкретного сигнала и слабостью выборки.
- `frontend/` показывает отдельную панель `Recommendation quality segments`: качество по рынкам, таймфреймам, направлениям и типам сигналов выводится рядом с MTF/evidence, без raw JSON и без торговых расчетов на клиенте.
- `sql/migrations/20260505_v44_market_data_integrity_and_quality_segments.sql` добавляет `NOT VALID` CHECK-ограничения для OHLC/liquidity/outcome-метрик, индексы для integrity scan и views `v_recommendation_quality_segments_v44`, `v_recommendation_integrity_audit_v44`, `v_recommendation_contract_v44`. `NOT VALID` выбран намеренно: миграция безопасна для существующих БД, а очистку старых загрязненных строк можно выполнять отдельно до `VALIDATE CONSTRAINT`.

Публичный контракт рекомендаций остается `recommendation_v40`, чтобы не ломать существующий frontend/API. V44 — это совместимое расширение integrity, quality diagnostics и operator UX.

## Nested Trade Contract and Signal Payload Audit V45

V45 устраняет рассинхрон между top-level legacy-полями API и вложенным объектом `recommendation`, который использует торговый интерфейс. Теперь вложенный контракт самодостаточен: directional-рекомендация содержит `entry`, `stop_loss`, `take_profit`, `risk_reward`, `confidence_score`, `expires_at`, `price_actionability`, `contract_health` и объяснение в одном объекте. Frontend по-прежнему не рассчитывает торговые уровни самостоятельно и только отображает серверный контракт.

Что изменено:

- `app/trade_contract.py` добавляет `entry`, `stop_loss`, `take_profit` во вложенный объект `recommendation` и валидирует уровни именно внутри outbound-контракта. `REVIEW_ENTRY`/`RESEARCH_CANDIDATE` без вложенных уровней или с невозможной геометрией SL/TP получает `contract_health.ok=false`.
- Для не-entry статусов (`blocked`, `wait`, `expired`, `invalid`, `missed_entry`) контракт не должен показывать `trade_direction=long/short`; безопасное состояние — `no_trade`.
- `app/api.py` публикует совместимое расширение `nested_trade_levels_v45` в metadata и `/api/recommendations/active`, а `/api/system/warnings` сначала использует `v_recommendation_integrity_audit_v45`.
- `sql/migrations/20260505_v45_nested_trade_contract_and_signal_payload.sql` добавляет `NOT VALID` constraints для `signals.rationale`, индекс аудита payload и views `v_recommendation_integrity_audit_v45`, `v_recommendation_contract_v45`.
- `frontend/app.js` явно показывает уровни из вложенного контракта в guardrails-блоке и больше не пишет handled LLM-background состояние как browser `console.warn`.

Публичная версия контракта намеренно остается `recommendation_v40`, потому что это совместимое расширение без поломки существующих клиентов. Новые клиенты могут смотреть `compatible_extensions` и `ui_contract_extension=nested_trade_levels_v45`.

## Server Actionability and Price Gate Demotion V46

V46 закрывает UX/contract-рассинхрон: раньше `price_actionability` мог блокировать вход, но статус оставался `review_entry`. Теперь `REVIEW_ENTRY` существует только если текущая цена находится в серверной `entry_zone`.

Что изменено:

- `app/trade_contract.py` демотирует `price_status=extended` и `price_status=moved_away` в `missed_entry` с `trade_direction=no_trade`; оператор видит `NO_TRADE · ЖДАТЬ РЕТЕСТ`, а не ручной вход.
- Если текущая цена неизвестна (`price_status=unknown`), directional review демотируется в `wait/no_trade` до восстановления quote feed.
- `no_trade_reason` теперь получает конкретную причину price gate: `price_extended_wait_retest`, `price_moved_away` или `price_unknown`.
- `app/api.py` публикует compatible extension `server_actionability_v46`; `/api/system/warnings` сначала использует `v_recommendation_integrity_audit_v46`.
- `sql/migrations/20260505_v46_server_actionability_and_price_gate.sql` добавляет audit view для активных сигналов, где latest price уже вышла за server entry-zone.
- Frontend больше не формулирует `missed_entry` как потенциально догоняемую сделку: правильное действие — ждать ретест или пересчитать.

Практическое правило V46: `REVIEW_ENTRY` требует одновременно валидные уровни, неистекший TTL, `price_status=entry_zone`, `contract_health.ok=true` и приемлемый `net_risk_reward`. Всё остальное — не вход.

## Loss quarantine V43

Добавлен защитный слой против ситуации, когда стратегия формально прошла backtest/quality-gate, но последние реальные или paper-исходы похожих рекомендаций убыточны. Runtime собирает последние 20 завершенных исходов по ключу `category + symbol + interval + strategy + direction` и передает в операторский классификатор поля:

- `recent_outcomes_count`;
- `recent_loss_count`;
- `recent_loss_rate`;
- `recent_average_r`;
- `recent_profit_factor`;
- `recent_consecutive_losses`;
- `recent_last_evaluated_at`.

Если выполнено одно из условий ниже, рекомендация блокируется как `NO_TRADE` независимо от формального `APPROVED`:

- исходов не меньше `RECOMMENDATION_LOSS_QUARANTINE_MIN_TRADES`, доля убытков >= `RECOMMENDATION_LOSS_QUARANTINE_MAX_LOSS_RATE`, средний R <= `RECOMMENDATION_LOSS_QUARANTINE_MIN_EXPECTANCY_R`;
- подряд убыточных исходов >= `RECOMMENDATION_LOSS_QUARANTINE_CONSECUTIVE_LOSSES`.

Фронт показывает отдельную карточку `Loss quarantine`, а `/api/system/warnings` использует `v_recommendation_integrity_audit_v43`, если миграция применена. Это не заменяет полноценный risk review, но закрывает дефект, когда после серии фактических убытков система продолжала выдавать новые `REVIEW_ENTRY`.

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
- При одновременном касании SL и TP внутри одной OHLC-свечи безопаснее считать SL-first, чем завышать качество стратегии за счет недоказуемого TP-first.
- Если цена вышла из `entry_zone`, безопаснее демотировать directional review в `NO_TRADE/WAIT`, чем позволить оператору догонять рынок по устаревшей зоне входа.
- `confidence_score` — инженерный скоринг качества сетапа, а не точная вероятность прибыли; это явно возвращается backend и показывается во frontend в `operator_risk_disclosures`.

## Известные ограничения

- Нет WebSocket/account reconciliation, потому что реального исполнения нет.
- Нет private Bybit API, управления позициями и ордерами.
- LLM evidence зависит от локального Ollama-compatible endpoint и не является источником торгового приказа.
- ML evidence зависит от доступности истории и актуальности model_runs.
- Полная production-эксплуатация требует мониторинга PostgreSQL, API rate limits, alerting и резервного восстановления.
- OHLC-backtest не восстанавливает реальный внутрисвечный путь цены; неоднозначные SL/TP-свечи помечаются и штрафуются, но окончательная верификация требует более детальных данных.
- V46 price-gate audit использует latest candle close как доступную публичную цену; для production-терминала желательно добавить websocket/mark-price feed, но без автоматического исполнения.

## Troubleshooting

- Пустая очередь: проверьте свежесть свечей, MTF entry interval, liquidity filters, `MAX_SIGNAL_AGE_HOURS` и наличие хотя бы одного сетапа после `trend_continuation_setup`.
- Все кандидаты `НЕТ ВХОДА`: откройте checklist/reasons; чаще всего причина в stale данных, MTF conflict, низком R/R, liquidity/spread или выходе цены из entry-zone.
- `Quality refresh` долго идет: это штатная фоновая операция; смотрите статус в Strategy Lab или `/api/strategies/quality/refresh/status`. Если часто видите `partial=true`, уменьшите `STRATEGY_QUALITY_REFRESH_LIMIT` или увеличьте `STRATEGY_QUALITY_REFRESH_TIME_BUDGET_SEC`.
- Ошибка Bybit: уменьшите число symbols/intervals/days, проверьте rate limits и сеть.
- Ошибка PostgreSQL: проверьте `.env`, доступность БД и выполните `python run.py migrate --list`; для новой БД используйте `python run.py migrate --init-schema`.
- LLM unavailable: проверьте `OLLAMA_BASE_URL`, модель и timeout.

## V51: server-side gate для operator `paper_opened`

V51 закрывает критичный разрыв между frontend UX и API: отключенная кнопка в браузере больше не является единственной защитой от фиксации paper-входа. `POST /api/recommendations/{signal_id}/operator-action` теперь серверно отклоняет `paper_opened`, если рекомендация не является actionable `REVIEW_ENTRY`.

Что изменено:

- `paper_opened` принимается только при `recommendation_status=review_entry`, `is_actionable=true`, `contract_health.ok=true`, `price_status=entry_zone`, торговом направлении `long/short` и отсутствии красных пунктов server-owned `operator_checklist`;
- для paper-входа обязательна положительная цена аудита: `observed_price` из клиента или серверный `last_price`;
- payload в `recommendation_operator_actions` сохраняет `is_actionable`, `contract_health_ok`, `price_status`, `market_freshness`, `net_risk_reward`;
- миграция `20260505_v51_operator_action_server_gate.sql` добавляет DB CHECK-ограничения и audit-view `v_recommendation_integrity_audit_v51`; audit-view сохраняет порядок и типы колонок `v_recommendation_integrity_audit_v48`, поэтому безопасно накатывается поверх уже примененной V48;
- `/api/system/warnings` сначала использует V51 audit-view;
- frontend сообщает, что paper-вход повторно проверяется сервером, а `manual_review` остается доступным даже для blocked/research сетапов, потому что ручной разбор не является входом.

Практическое правило V51: невозможно зафиксировать paper-вход через API, если серверный recommendation contract не разрешил actionable ручную проверку входа.

## V52: operator risk disclosure и целостность legacy paper trades

V52 закрывает два оставшихся риска советующей системы: оператор мог видеть сильный-looking сигнал без структурированного предупреждения о природе рекомендации, а legacy-таблица `paper_trades` могла принять математически невозможную бумажную сделку как аналитический факт.

Что изменено:

- `app/trade_contract.py` добавляет совместимое расширение `operator_risk_disclosure_v52` и поле `operator_risk_disclosures` в каждый outbound `recommendation` contract;
- каждый контракт явно сообщает, что система не отправляет ордера на Bybit, `confidence_score` не является вероятностью прибыли, а перед входом нужен ручной контроль цены, spread, ликвидности и новостного риска;
- для `NO_TRADE`, blocked, expired, stale, invalid и missing-TTL состояний disclosure получает `blocks_entry=true`, чтобы UI не оставлял двусмысленности;
- empty/no-signal state теперь тоже имеет канонический `NO_TRADE` snapshot с risk disclosure, а не только пустой список;
- frontend показывает блок `Risk disclosure` в деталях trade ticket и no-trade snapshot; если серверный `recommendation` contract отсутствует, UI помечает это как красный guardrail и не строит торговые выводы из legacy-полей;
- `sql/migrations/20260505_v52_operator_risk_disclosure_and_paper_trade_integrity.sql` добавляет CHECK-ограничения `ck_paper_trades_direction_v52`, `ck_paper_trades_positive_numbers_v52`, `ck_paper_trades_level_side_v52`, индекс `idx_paper_trades_advisory_audit_v52` и audit-view `v_recommendation_integrity_audit_v52`;
- `/api/recommendations/contract` публикует `operator_risk_disclosure_extension` и `operator_risk_audit_view`; `/api/system/warnings` сначала проверяет V52 audit-view.

Практическое правило V52: frontend не имеет права превращать legacy/raw поля в торговую рекомендацию. Если сервер не вернул полный contract с disclosure/checklist/health, оператор видит защитное состояние и должен обновить данные или проверить backend.


## Риск-дисклеймер

Крипторынок высокорисковый. Проект предназначен для исследовательской и операторской поддержки принятия решений. Любые рекомендации должны проверяться человеком; ответственность за сделки и капитал остается на операторе.

## V47: server-owned operator checklist и полный nested recommendation identity

В этой ревизии усилен API/UI-контракт советующей системы:

- nested `recommendation` теперь самодостаточно содержит `category`, `symbol`, `interval`, `strategy`, `created_at`, `bar_time`;
- backend формирует `operator_checklist` со статусами `pass` / `warn` / `fail` для финального server gate, identity, direction, уровней, TTL, price gate, R/R, confidence, MTF, liquidity/spread, strategy quality и статистической уверенности;
- frontend сначала отображает server-owned `operator_checklist` и использует локальный чек-лист только как legacy fallback для старых API-ответов;
- `contract_health` теперь считает отсутствие `operator_checklist` ошибкой контракта и не позволяет `REVIEW_ENTRY` без зелёного server price gate в чек-листе;
- SQL-миграция `20260505_v47_operator_checklist_contract.sql` публикует `v_recommendation_integrity_audit_v47` и `v_recommendation_contract_v47`.

Это дополнительно снижает риск рассинхрона, при котором браузер мог заново интерпретировать risk/quality/freshness-поля и показывать оператору отличающийся от backend смысл рекомендации.

## V48: reference-price freshness guard

V48 закрывает отдельный риск, который не покрывался одним `expires_at`: торговая идея могла оставаться в активном TTL, но reference price для server price gate уже был старым или без проверяемого timestamp. Теперь `REVIEW_ENTRY` требует не только валидные уровни и `price_status=entry_zone`, но и свежий `market_freshness.status=fresh`.

Что изменено:

- `app/trade_contract.py` добавляет совместимое расширение `market_price_freshness_v48` без смены публичного `recommendation_v40`.
- В каждый nested `recommendation` добавлены `market_freshness`, `last_price_age_seconds`, `last_price_max_age_seconds`; эти поля показывают источник timestamp (`last_price_time`, `bar_time` или legacy fallback), фактический возраст цены и допустимый бюджет.
- Если timestamp reference price отсутствует, находится в будущем или старше бюджета `2 × interval + 5 минут` с нижней границей 10 минут, runtime выставляет `price_status=stale`, блокирует `price_actionability` и демотирует потенциальный `REVIEW_ENTRY` в безопасный `NO_TRADE/expired`.
- Серверный `operator_checklist` получил пункт `market_freshness`; frontend показывает его в карточке, ticket detail и telemetry без повторного расчета торговой логики.
- `sql/migrations/20260505_v48_market_price_freshness_contract.sql` и `sql/schema.sql` публикуют `v_recommendation_integrity_audit_v48` и `v_recommendation_contract_v48`, чтобы БД-аудит находил активные рекомендации без свежей reference price.
- `GET /api/recommendations/contract` публикует `market_freshness_extension=market_price_freshness_v48` и `market_freshness_audit_view=v_recommendation_integrity_audit_v48`; `/api/system/warnings` использует V48 при наличии миграции.

Практическое правило V48: активный TTL не равен актуальной цене. Если price timestamp устарел или непроверяем, оператор видит блокировку входа, а не зелёную рекомендацию.

## V54: quote freshness contract, deterministic quality drawdown и primary next action

V54 закрывает три эксплуатационных риска советующей trading-СΠПР:

- `/api/quotes/latest` больше не использует `MAX_SIGNAL_AGE_HOURS` как признак свежести цены. Quotes endpoint теперь публикует тот же interval-aware freshness payload, что и recommendation contract: `market_freshness`, `age_seconds`, `max_age_seconds`, `freshness_reason`, `data_status`. Практическое правило: свежесть reference price — это `2 закрытых бара + 5 минут`, а не общий TTL исследовательской идеи.
- Recommendation quality drawdown стал детерминированным: R-кривая упорядочивается по `evaluated_at, signal_id`, чтобы несколько исходов с одинаковым timestamp не меняли max drawdown в зависимости от плана PostgreSQL.
- Каждый outbound recommendation contract получил `primary_next_action`. Для actionable `REVIEW_ENTRY` это `paper_opened`, но только как аудируемая paper-отметка после ручной проверки; ордера на Bybit не отправляются. Список `next_actions` сохраняется для UI и обратной совместимости.

Новые DB-объекты:

- `v_market_quote_freshness_audit_v54` — аудит stale/future/invalid latest quotes по рынкам и таймфреймам;
- `v_recommendation_quality_drawdown_v54` — recommendation-level drawdown в R с детерминированным порядком;
- `v_recommendation_contract_v54` — справочный contract-view политики V54.

Проверка V54:

```bash
python run.py migrate
python -m pytest -q tests/test_v54_quote_freshness_and_quality_drawdown.py
node --check frontend/app.js
```
