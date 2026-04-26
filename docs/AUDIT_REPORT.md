# Red-team аудит Bybit ML/LLM Research Lab — ревизия 2026-04-26

## Краткое резюме до исправлений

Проект был полезным research-стендом для ручного оператора: публичный Bybit REST ingestion, rule-based стратегии, backtest, ML-классификатор, sentiment и LLM-разбор кандидатов. При этом для practically production-ready рекомендательной системы оставались дефекты, способные привести к неверной рекомендации, дублированию данных, гонкам идентификаторов, silent failure и некорректному восприятию границ системы.

Ключевой статус после ревизии: **система приведена к более безопасному recommendation-only состоянию, но не является live-trading/order-execution системой**. В проекте нет account-state reconciliation, WebSocket order reconciliation, durable order outbox, idempotency keys для биржевых ордеров и grid-bot lifecycle FSM. Это зафиксировано явно, чтобы не было ложного ощущения готовности к автоматическому исполнению.

## Найденные проблемы по критичности

### Critical

1. **Использование незакрытой Bybit-свечи для сигналов.** Публичный kline endpoint может вернуть текущий бар; его close не финален. Исправлено: `sync_candles()` теперь сохраняет только закрытые свечи через `_is_closed_candle()`.
2. **Race condition при привязке сделок backtest к run_id.** После INSERT использовался `SELECT id FROM backtest_runs ORDER BY id DESC LIMIT 1`, что при параллельных запусках могло взять чужой id. Исправлено: добавлен `execute_many_values_returning()` и `INSERT ... RETURNING id`.
3. **Отсутствие финального фильтра непротиворечивости торгового сигнала.** Стратегии могли вернуть физически невозможные уровни из-за дефекта данных/логики. Исправлено: `validate_signal()` проверяет direction, confidence, entry, ATR и порядок SL/TP перед выдачей оператору.

### High

1. **Spot universe ошибочно требовал open interest.** Для spot-инструментов OI не является обязательным полем. Исправлено: OI-фильтр применяется только для `linear`/`inverse`.
2. **Inverse universe фактически отбрасывался USDT-фильтром.** Исправлено: для `inverse` разрешены USD-инструменты, для `linear/spot` сохранен USDT-фокус текущей конфигурации.
3. **RSS fallback URL строился через Python `hash()`.** Он рандомизирован между процессами, поэтому одинаковые новости могли дублироваться после рестарта. Исправлено: deterministic SHA-256 synthetic URL.
4. **Фоновые LLM-запуски не имели явной защиты от перекрытия.** Исправлено: добавлен non-blocking `_run_lock` и безопасный `already_running` результат.
5. **`app.ml` создавал `models/` при импорте.** В read-only окружении импорт падал до запуска диагностики. Исправлено: каталог создается лениво только при записи модели.

### Medium

1. **Bybit transient retCode был неполным.** Добавлен `10429` как retryable system-level frequency protection.
2. **Сетевые сбои sentiment-источников частично замалчивались.** Добавлено warning-логирование для GDELT/RSS/CryptoPanic.
3. **Конфиг и `.env.example` расходились по дефолтной LLM-модели.** Исправлено: дефолт `OLLAMA_MODEL` приведен к `qwen3:8b`.
4. **Название `MAX_DAILY_DRAWDOWN` вводило в заблуждение.** Реально это backtest-level risk halt от стартового equity, а не календарный дневной лимит. Добавлен алиас `MAX_BACKTEST_DRAWDOWN`, старое имя оставлено для совместимости.

### Low

1. В документации были устаревшие ожидания по числу тестов (`24 passed`). Обновлено до `47 passed`.
2. В `STRATEGY_MAP` для history-dependent стратегий были заглушки `lambda row: None`; оставлен явный комментарий, `_build_signal()` продолжает передавать history.

## Что исправлено

- `app/bybit_client.py`: закрытость свечей, retryable `10429`, корректный symbol-фильтр для inverse/spot, spot liquidity без OI-требования.
- `app/db.py`: `execute_many_values_returning()` для безопасного RETURNING после batch insert.
- `app/backtest.py`: backtest-run id берется из `RETURNING id`, устранена гонка `ORDER BY id DESC`.
- `app/strategies.py`: `validate_signal()` и фильтрация невалидных рекомендаций до сохранения/вывода.
- `app/sentiment.py`: deterministic synthetic URL для новостей без URL, warning-логирование сетевых сбоев.
- `app/llm_background.py`: защита от перекрывающихся LLM-циклов.
- `app/ml.py`: ленивое создание `models/` только перед сохранением модели.
- `app/config.py`, `.env.example`/README-документация: актуализированы дефолты и описание risk/backtest режима.

## Что добавлено

- Unit-тест закрытия свечей Bybit перед сохранением.
- Unit-тест валидации невозможных SL/TP.
- Unit-тест spot liquidity без open-interest requirement.
- Unit-тест стабильного synthetic news URL и fallback-логики.
- Unit-тест защиты LLM-background от overlapping run.
- Regression-тест импорта `app.ml` без записи в ФС уже покрывается `tests/test_warning_cleanup.py` после исправления.

## Торгово-логические ошибки

1. Сигналы могли строиться на незакрытой свече.
2. Backtest-run сделки могли быть привязаны к чужому run при параллельном запуске.
3. Перед persist не было единого контракта валидности рекомендаций.
4. Spot/inverse liquidity universe был некорректен из-за USDT/OI допущений.
5. `MAX_DAILY_DRAWDOWN` был не дневным лимитом, а остановкой backtest от стартового equity.

## Архитектурные ошибки

1. Слой рекомендаций и термины live-trading были недостаточно разведены в документации.
2. ML-модуль имел побочный эффект записи в ФС при импорте.
3. History-dependent стратегии в `STRATEGY_MAP` были представлены как одноаргументные заглушки, что ухудшало читаемость контракта.
4. Фоновый LLM-сервис не имел явного single-flight guard.

## Проблемы надежности/отказоустойчивости

1. Неполный список retryable Bybit retCode.
2. Silent failure в sentiment ingestion без логов.
3. Дедупликация новостей без URL была нестабильной между рестартами.
4. Не было защиты от overlapping LLM cycles.
5. Полная live-trading отказоустойчивость отсутствует намеренно, потому что проект не исполняет ордера.

## Проблемы тестового покрытия

До ревизии не хватало regression-тестов на:

- незакрытые Bybit-свечи;
- невозможные уровни SL/TP;
- spot liquidity без OI;
- стабильность dedup-key для новостей;
- overlapping LLM-background запуск;
- race-safe backtest id через RETURNING.

После ревизии эти сценарии покрыты тестами. Grid-bot тесты не добавлены как полноценные сценарии исполнения, потому что grid-bot/order lifecycle в проекте отсутствует. Это зафиксировано как остаточный риск/граница системы, а не додуманная реализация.

## Расхождения код ↔ документация

1. Ожидаемое число тестов было устаревшим (`24 passed`) — обновлено до `47 passed`.
2. LLM model default в `.env.example` и коде расходился — исправлено.
3. Risk parameter `MAX_DAILY_DRAWDOWN` описывал не календарный дневной лимит — добавлен `MAX_BACKTEST_DRAWDOWN` и пояснение.
4. Live-trading/idempotency/reconciliation отсутствуют — теперь явно указано, что проект только рекомендует оператору.

## Результаты проверки

- Статическая компиляция: `python -m compileall -q app tests run.py install.py sitecustomize.py` — успешно.
- Тесты по файлам через `pytest.main`: **47 passed**.
- Проверенные группы:
  - `tests/test_core_safety.py`: 9 passed;
  - `tests/test_db_diagnostics.py`: 1 passed;
  - `tests/test_frontend_decision_ui.py`: 5 passed;
  - `tests/test_launcher_scripts.py`: 6 passed;
  - `tests/test_llm_background.py`: 3 passed;
  - `tests/test_llm_background_concurrency.py`: 1 passed;
  - `tests/test_llm_serialization.py`: 2 passed;
  - `tests/test_loky_sitecustomize.py`: 2 passed;
  - `tests/test_news_dedup.py`: 2 passed;
  - `tests/test_runtime_environment.py`: 3 passed;
  - `tests/test_universe.py`: 1 passed;
  - `tests/test_warning_cleanup.py`: 4 passed;
  - `tests/smoke_test.py`: 1 passed.

## Остаточные риски

1. Нет live-order execution, exchange-side idempotency, account/order WebSocket reconciliation, durable outbox, kill-switch и post-trade audit. Для рекомендательной системы это допустимо; для автоматической торговли — блокер.
2. Нет grid-bot state machine. Добавлять тесты grid-ботов без реализации было бы фиктивным покрытием.
3. Backtest остается баровым и консервативным при same-bar SL/TP ambiguity, но не моделирует очередь заявок, funding settlement, ликвидационные риски, проскальзывание по order book и частичные исполнения.
4. ML-модель остается исследовательской: нет walk-forward retraining orchestration, model registry, drift detection и production monitoring.
5. LLM-слой не должен рассматриваться как источник торгового исполнения; это только текстовый риск-разбор.

## Принятые допущения

1. При неоднозначности внутри одной свечи backtest выбирает stop-loss первым как более консервативный вариант.
2. Сигналы строятся только на закрытых свечах.
3. Spot-инструменты не требуют open interest; linear/inverse требуют.
4. Старое имя `MAX_DAILY_DRAWDOWN` сохранено как fallback для совместимости, но рекомендуемое имя — `MAX_BACKTEST_DRAWDOWN`.
5. Никакая бизнес-логика live-trading и grid-bot исполнения не додумывалась молча.

## Дополнение ревизии 2026-04-26: автоматизм сигналов и фоновых контуров

### Краткое резюме до исправлений

Пользовательское ожидание автоматического обновления было обоснованно: проект показывал фоновый backtest и фоновую LLM-оценку, но свежие рыночные данные и новые рекомендации строились только ручными действиями оператора. Фронтенд периодически перечитывал API, однако это был auto-refresh экрана, а не auto-refresh сигналов. LLM могла анализировать только уже существующие кандидаты из `research/rank`; она не инициировала загрузку рынка и построение новых сигналов.

### Critical

1. **Неполный автоматический контур сигналов.** Без ручного `POST /api/sync/market` и `POST /api/signals/build` рекомендации могли оставаться устаревшими, а LLM/backtest работали по старому candidate set. Исправлено: добавлен `app.signal_background.SignalAutoRefresher`, который выполняет цепочку `universe -> market/sentiment -> signals -> backtest/LLM`.

### High

1. **LLM-background смешивал shutdown и run-now в одном `threading.Event`.** Это создавало неоднозначность: ручной внеочередной запуск и остановка сервиса были представлены одним и тем же флагом. Исправлено: LLM-background переведен на `Condition` с отдельным `_stop_requested` и `_run_requested`.
2. **`app.api` импортировал sklearn/joblib на старте через `app.ml`.** ML-зависимости тяжелые и не нужны для основной витрины рекомендаций. Исправлено: `train_model` и `predict_latest` импортируются лениво только внутри `/api/ml/*`.

### Medium

1. **UI показывал статусы backtest/LLM, но не показывал состояние автоматического построения рекомендаций.** Исправлено: добавлен статус `Signals` и кнопка `Авто-рекомендации сейчас`.
2. **После ручного `Build signals` будился backtest, но LLM мог ждать своего планового интервала.** Исправлено: при появлении сигналов API будит и backtest, и LLM.

### Что исправлено и добавлено

- `app/signal_background.py`: новый single-flight фоновый сервис рекомендаций.
- `app/main.py`: запуск/остановка `signal-auto-refresher` вместе с backtest/LLM сервисами.
- `app/api.py`: endpoints `GET /api/signals/background/status`, `POST /api/signals/background/run-now`; ленивый импорт ML.
- `app/llm_background.py`: разделены stop/run-now механизмы.
- `frontend/index.html`, `frontend/app.js`: статус автоматических сигналов и ручной внеочередной запуск.
- `.env.example`, `README.md`: параметры `SIGNAL_AUTO_*`, новый фактический pipeline и границы автоматизма.
- `tests/test_signal_background.py`: тесты single-flight, полного фонового pipeline и fallback выбора символов.
- `tests/test_llm_background_concurrency.py`: regression-тест, что `request_run()` LLM не выставляет shutdown-флаг.

### Остаточные риски

1. Контур остается polling/REST-based; WebSocket market data и exchange/account reconciliation отсутствуют намеренно, потому что проект не исполняет ордера.
2. Sentiment-синхронизация в фоне может быть медленной или частично падать из-за внешних источников; она не блокирует рыночные сигналы и фиксируется warning'ами.
3. Автоматическое обучение ML не включено: это оставлено ручным, чтобы не подменять модель без отдельного model registry, walk-forward контроля и drift-monitoring.
4. Grid-bot/order lifecycle по-прежнему отсутствует; тесты grid-исполнения не добавлялись, чтобы не создавать фиктивное покрытие несуществующего модуля.

### Принятые допущения

1. Наиболее безопасное поведение при пустом/недоступном universe: сначала последний сохраненный universe, затем `DEFAULT_SYMBOLS`; при `REQUIRE_LIQUIDITY_FOR_SIGNALS=true` fallback не обходит liquidity gate.
2. Фоновый сигналинг ограничен `SIGNAL_AUTO_MAX_SYMBOLS` и коротким окном `SIGNAL_AUTO_SYNC_DAYS`, чтобы не превратить UI-сервис в тяжелый batch-ingestion.
3. LLM остается объяснительным risk-review, а не источником торговой команды.

### Результаты проверки

- `python -m compileall -q app tests run.py install.py sitecustomize.py` — успешно.
- `node --check frontend/app.js` — успешно.
- Тестовый набор содержит 47 содержательных тестов, включая 4 новых regression/scenario-теста для автоматического signal pipeline и LLM wakeup/shutdown.

---

## Предыдущая история аудита проекта

# Audit report v2.1

## Резюме до исправлений

Проект был полезным исследовательским стендом, но не production-ready даже для строгого paper-research: бэктест завышал качество за счёт входа на уже известной свече, история funding/OI могла тихо обрезаться лимитами Bybit API, core universe мог включать непроверенные инструменты, отсутствовали retry/backoff и полноценная валидация входных параметров.

## Critical

1. Lookahead/optimistic execution в бэктесте: сигнал и вход использовали одну и ту же закрытую свечу.
2. ML target помечал последние `horizon_bars` строк как отрицательные, хотя будущая доходность неизвестна.
3. Funding/open interest загружались одним запросом с лимитом 200, что для 90 дней на 1h/OI теряло большую часть истории.
4. Нет notional/leverage cap в расчёте позиции.

## High

1. Отсутствовал retry/backoff Bybit API.
2. Core symbols могли обходить liquidity eligibility.
3. PreLaunch-инструменты могли пройти фильтр.
4. Сигналы дублировались при повторном запуске.
5. Drawdown считался по realized equity без mark-to-market открытой позиции.
6. Research ranking учитывал потенциально устаревшие сигналы.

## Medium

1. Недостаточная валидация category/interval/symbol/limit/days.
2. Неявное допущение по порядку достижения SL/TP внутри свечи не было документировано.
3. Отсутствовали индексы для частых lookup-запросов backtest/model/signals.
4. Ошибки отсутствующих optional dev-зависимостей мешали минимальному тестовому импорту.

## Low

1. Термин `inserted` для upsert-операций был неточным.
2. README не фиксировал новые safety-допущения.
3. Часть комментариев не объясняла именно риск-смысл нетривиальной логики.

## Исправлено

- Бэктест: вход на следующей свече, slippage, mark-to-market equity, forced end-of-data close, notional/leverage cap, conservative same-bar SL/TP rule.
- Bybit REST: retry/backoff, transient retCode handling, HTTP 429/5xx handling, non-JSON guard.
- Market sync: chunked funding/OI history sync.
- Universe: исключение PreLaunch, запрет unverified core symbols по умолчанию.
- Signals: `bar_time`, idempotent upsert, unique partial index.
- ML: корректное исключение строк без будущей доходности; guard на одно-классовую выборку.
- API: нормализация и ограничения входных параметров.
- Ranking: свежесть сигналов, штрафы за низкую ликвидность и недостаточное число сделок.
- Тесты: 11 содержательных unit/scenario-тестов, включая проверки новых кроссплатформенных launcher-скриптов.

## Принятые допущения

- При достижении SL и TP внутри одной свечи выбирается SL.
- Core symbols должны проходить liquidity-фильтр, если не включён явный manual override.
- Отсутствие liquidity snapshot блокирует сигнал, потому что недоказанная ликвидность считается дефектом безопасности.
- Проект остаётся рекомендателем, а не автономным торговым исполнителем.

## Оставшиеся риски

- Нет live execution FSM, durable outbox, exchange reconciliation, account balance reconciliation и kill-switch, потому что проект не должен отправлять реальные ордера.
- Нет WebSocket layer; polling может быть недостаточен для исполнения, но допустим для research.
- Нет walk-forward и полноценного portfolio-level risk model.
- Сентимент остаётся шумным и должен быть вспомогательным, а не определяющим сигналом.

## Результаты проверок

- `python -m compileall -q app tests`: успешно.
- `python -m pytest -q`: `47 passed`.

Примечание: в контейнере pytest выдал только предупреждение о невозможности записи cache в .pytest_cache; на результат тестов это не повлияло.

## Дополнение: диагностика PostgreSQL на Windows

По результатам проверки реального запуска на Windows добавлена защита от неинформативного `UnicodeDecodeError` при подключении `psycopg2` к PostgreSQL. Такая ошибка может появляться до выполнения SQL, когда libpq возвращает исходную ошибку подключения в локальной кодировке Windows, а Python-драйвер пытается декодировать ее как UTF-8.

Внесено:

- подключение теперь выполняется через именованные параметры, а не через единую DSN-строку;
- пароль не выводится в диагностике;
- добавлен TCP-preflight для случая незапущенного/недоступного PostgreSQL;
- `app.init_db` теперь возвращает понятное сообщение и код выхода `2` вместо сырого traceback;
- добавлен `app.db_check` и команда `python run.py db-check`;
- README и Windows-инструкция дополнены разбором ошибки и безопасным порядком проверки.

Оставшееся ограничение: проект не создает PostgreSQL-сервер, роль и базу автоматически, потому что это требует административных прав и зависит от политики установки PostgreSQL. Для локальной разработки рекомендован ASCII-пароль и `.env` в UTF-8.

## Дополнение: очистка runtime-предупреждений pandas

По результатам реального запуска на Windows обнаружены повторяющиеся предупреждения:

- `pandas.read_sql_query` предупреждал о неподдерживаемом raw `psycopg2` connection;
- `features.py` генерировал `FutureWarning` pandas при `ffill().fillna(False)` для object-колонки `is_eligible`.

Исправлено:

- `app.db.query_df` переведен на прямое чтение через DB-API cursor с сохранением SQL-параметризации; это убирает массовый `UserWarning` без добавления тяжелой зависимости SQLAlchemy;
- `is_eligible` теперь приводится через pandas `BooleanDtype`, а затем к обычному `bool`; неизвестная ликвидность по-прежнему трактуется как `False`;
- добавлены тесты, которые запрещают возврат к `pandas.read_sql_query` с raw connection и проверяют отсутствие `FutureWarning` при сборке market frame.

Результаты дополнительной проверки в целевой среде должны быть:

- `python -m compileall -q app tests`: успешно;
- `python -m pytest -q`: `47 passed`.

## Дополнение: подавление joblib/loky warning на Windows

При реальном запуске `POST /api/ml/train` на Windows обнаружено предупреждение `joblib/loky`: библиотека пыталась вызвать `wmic CPU Get NumberOfCores /Format:csv`, но `wmic` отсутствовал, после чего joblib возвращался к числу логических ядер. Обучение при этом завершалось успешно (`200 OK`), однако warning засорял лог и мог скрывать значимые сообщения.

Исправлено:

- добавлен `app.runtime.configure_runtime_environment()`;
- `LOKY_MAX_CPU_COUNT` задается до импорта `sklearn/joblib`;
- пользовательские `LOKY_MAX_CPU_COUNT` и `ML_MAX_CPU_COUNT` не перетираются;
- добавлен вывод ML CPU-настроек в `python run.py doctor`;
- `.env.example`, README и Windows-инструкция дополнены параметром `ML_MAX_CPU_COUNT`;
- добавлены regression-тесты runtime-настройки.

Результаты дополнительной проверки в целевой среде должны быть:

- `python -m compileall -q app tests`: успешно;
- `python -m pytest -q`: `47 passed`.

## Дополнение: усиленное подавление warning joblib/loky на Windows

После проверки на пользовательском Windows-стенде выяснилось, что одной ранней установки `LOKY_MAX_CPU_COUNT` недостаточно для всех связок Windows/Python/joblib: в некоторых сценариях loky все равно пытается определить физические ядра через отсутствующий `wmic` и печатает `UserWarning`.

Исправление усилено:

- добавлен корневой `sitecustomize.py`, который Python импортирует до запуска модулей проекта;
- `LOKY_MAX_CPU_COUNT` задается еще до импорта `app`, `uvicorn`, `sklearn` и `joblib`, если пользователь не задал его вручную;
- добавлен точечный фильтр только для известного warning `joblib.externals.loky.backend.context` об отсутствующем `wmic`;
- фильтр продублирован в `app.runtime.configure_runtime_environment()` как резервный уровень защиты;
- добавлены regression-тесты, проверяющие раннюю настройку окружения и подавление именно этого предупреждения.

## Дополнительное исправление loky/joblib для Windows reload

Повторная проверка показала, что значение `LOKY_MAX_CPU_COUNT`, равное числу логических ядер, не всегда предотвращает попытку `joblib/loky` определить физические ядра через `wmic`. В Windows-средах без `wmic` это снова давало шумный warning при ML-операциях, особенно при прямом запуске `python -m uvicorn ... --reload`.

Исправление: автоматический дефолт теперь намеренно меньше `os.cpu_count()` и ограничен 4 потоками. Такой режим снижает локальную нагрузку и предотвращает ветку loky с вызовом `wmic`. В `run.py` переменная дополнительно передается в окружение дочернего процесса, включая reloader Uvicorn.

## Дополнение: очистка pandas FutureWarning в ML-инференсе

При реальном вызове `GET /api/ml/predict/latest` на Windows обнаружен отдельный `FutureWarning` pandas в `app/ml.py`: одиночная строка `latest[FEATURE_COLUMNS].to_frame().T` имела object dtype, а последующий `fillna(0.0)` полагался на неявный downcast.

Исправлено:

- добавлен `features.prepare_feature_matrix()`, который явно приводит все ML-признаки через `pd.to_numeric(errors="coerce")`, заменяет бесконечности и только затем заполняет пропуски;
- `build_ml_dataset()` и `predict_latest()` используют один и тот же безопасный путь подготовки feature matrix;
- `predict_latest()` стал устойчивее к разным формам результата `predict_proba`, извлекая вероятность через `[0][1]`;
- добавлены regression-тесты на отсутствие `FutureWarning` для object-признаков и ML-инференса.

Результаты дополнительной проверки:

- `py_compile`: успешно для измененных модулей и тестов;
- `tests/test_warning_cleanup.py`: `4 passed`;
- полный набор содержит 24 теста.

## Дополнительное исправление: JSON-нормализация LLM brief

Обнаружено по runtime-логу Windows: endpoint `POST /api/llm/brief` возвращал `500 Internal Server Error`, если payload содержал `datetime` из PostgreSQL-строки сигнала. Причина — прямой `json.dumps(payload)` в `app.llm.market_brief`, тогда как стандартный JSON encoder Python не сериализует `datetime`, `date`, `Decimal`, numpy/pandas-типы и ряд других объектов.

Исправление:
- добавлен `app.serialization.to_jsonable()` для рекурсивного приведения DB/pandas/numpy значений к JSON-совместимому виду;
- `market_brief()` теперь сериализует уже нормализованный payload;
- `app.db.json_safe()` оставлен как совместимый wrapper на общий serializer;
- добавлены regression-тесты на `datetime`, `date`, `time`, `Decimal`, `UUID`, numpy scalar/array, pandas `Timestamp` и `pd.NA`.

Безопасное допущение: неизвестные объектные типы переводятся в строку, потому что для LLM-brief это безопаснее, чем пользовательский 500 и потеря диагностического сценария. Торговые решения от этого не исполняются автоматически.

## UI/UX redesign: Decision Cockpit

Фронтенд переработан из технической таблицы в decision cockpit для ручного оператора. Главный экран теперь сначала показывает итоговый статус кандидата (`ПРОВЕРИТЬ`, `НАБЛЮДАТЬ`, `ЗАПРЕТ`), оценку, направление, план сделки, risk/reward, ограничения позиции, причины сигнала и стоп-факторы. Служебные таблицы universe/ranking/signals перенесены в раскрываемый блок технических деталей, чтобы не мешать принятию решения.

Важно: интерфейс не отправляет ордера и не создает ботов автоматически. Статус `ПРОВЕРИТЬ` означает только, что кандидата можно передать оператору на ручную проверку стакана, новостей, риска портфеля и актуальности цены.



## UI/UX redesign 2: Operator Workstation

После практической оценки Decision Cockpit был дополнительно упрощен. Предыдущий экран все еще перегружал оператора: таблицы, операции и вспомогательная аналитика конкурировали с главным решением.

Что изменено:

- интерфейс переориентирован на один рабочий сценарий: очередь кандидатов → выбранный сетап → чек‑лист допуска → trade ticket → протокол оператора;
- базовое состояние теперь всегда безопасное: `НЕТ ВХОДА`;
- любые красные пункты чек‑листа явно запрещают передачу сетапа на создание бота;
- технические таблицы и журнал больше не находятся на основном пути принятия решения и скрыты в `details`;
- операции загрузки данных скрыты в отдельном drawer, чтобы рабочий экран не был панелью администрирования;
- карточки кандидатов показывают только decision label, score, direction, confidence, R/R и spread;
- LLM brief вызывается только для выбранного сетапа и получает уже рассчитанный operator decision/checklist.

Безопасное допущение: интерфейс намеренно не пытается сделать кнопку «войти». Даже статус `К ПРОВЕРКЕ` означает только допуск к ручной проверке оператором.

## Дополнение: фоновая LLM-оценка и исправление UX-сценария

Проблема: LLM-разбор был привязан к ручной кнопке и не было очевидно, продолжается ли оценка кандидатов в фоне. Это создавало неверный рабочий сценарий: оператор должен был сам инициировать анализ каждого сетапа, а интерфейс не показывал жизненный цикл LLM-оценки.

Исправлено:

- добавлена таблица `llm_evaluations`;
- добавлен `app/llm_background.py` с daemon-loop и worker-thread'ами;
- FastAPI запускает/останавливает фоновый LLM-сервис через lifespan;
- `research/rank` возвращает актуальные поля `llm_status`, `llm_brief`, `llm_error`, `llm_updated_at`;
- добавлены endpoints `/api/llm/background/status`, `/api/llm/background/run-now`, `/api/llm/evaluations/latest`;
- UI больше не просит вручную формировать brief по каждому сетапу, а показывает сохраненный фоновый вердикт;
- ручная кнопка оставлена только как принудительный refresh фонового цикла.

Историческое замечание: на этом этапе был автоматизирован только LLM-анализ кандидатов. В последующих правках добавлен отдельный безопасный `signal-auto-refresher`, который обновляет рынок/сигналы без отправки ордеров и с single-flight защитой.


## Дополнение по автоматическому backtest

После повторной проверки требования backtest переведен из исключительно ручного режима в безопасный фоновый режим:

- добавлен `app/backtest_background.py` с сервисом `backtest-auto-runner`;
- FastAPI lifespan запускает и останавливает backtest-runner вместе с LLM-runner;
- `POST /api/signals/build` будит backtest-runner, если появились новые рекомендации;
- добавлены endpoints `GET /api/backtest/background/status` и `POST /api/backtest/background/run-now`;
- UI показывает состояние фонового backtest и кнопку `Авто-бэктест сейчас`;
- `.env.example` получил `BACKTEST_AUTO_*` параметры;
- добавлены regression-тесты на lock от overlap, SQL-критерий stale/missing backtest и частичный failure внутри цикла.

Принятое безопасное допущение: backtest автоматизирован как подготовка доказательной базы, но не как торговое действие. Он не отправляет ордера, не создает позиции, не меняет рекомендации и выполняется ограниченной последовательной очередью, чтобы не перегружать PostgreSQL/CPU.

Результат полного прогона после доработки: `47 passed`.

## Дополнение: multi-timeframe контур сигналов

После дополнительной проверки подтвержден дефект эксплуатации: система могла обновлять рекомендации только по одному `DEFAULT_INTERVAL`, а оператор ожидал более широкий автоматический анализ рынка. Это было особенно опасно тем, что UI и фоновые сервисы создавали ощущение автоматизма, но фактически смотрели в основном 1h-контур.

Исправлено:

- добавлен параметр `SIGNAL_AUTO_INTERVALS`, по умолчанию `15,60,240`;
- `signal-auto-refresher` теперь синхронизирует рынок, sentiment и сигналы по каждому TF независимо;
- `SIGNAL_AUTO_SYNC_DAYS` увеличен до 30, чтобы cold start давал достаточно баров для EMA200/минимального окна 250 свечей;
- `SIGNAL_AUTO_MAX_SYMBOLS`, `DYNAMIC_SYMBOL_LIMIT`, `UNIVERSE_LIMIT` увеличены до более практичных значений по умолчанию;
- ручные endpoints `/api/sync/market`, `/api/sync/sentiment`, `/api/signals/build` получили поддержку `intervals` без удаления старого `interval`;
- `/api/research/rank` получил поддержку `interval=15,60,240`, `interval=all`, `interval=multi`, `interval=mtf`;
- ranking/backtest/ML/LLM join'ы теперь учитывают `interval`, чтобы 15m-сигнал не получал доказательства от 1h backtest или ML-модели;
- фоновый LLM берет MTF-контекст из всех `SIGNAL_AUTO_INTERVALS`, но выбирает для оценки только 15m entry-кандидатов;
- UI теперь передает набор TF, но очередь решений показывает только 15m entry-рекомендации; 60m/240m видны только в MTF matrix как bias/regime-контекст.

Принятое безопасное допущение: MTF реализован как независимые сигналы по каждому таймфрейму, а не как скрытое смешивание признаков разных TF в одной рекомендации. Это проще проверять, воспроизводить и откатывать: каждая строка имеет собственный `interval`, `bar_time`, дедупликацию, backtest и LLM-оценку.


## Дополнение: intraday MTF-consensus и переработка operator cockpit

После включения нескольких таймфреймов выявлен следующий торгово-логический риск: независимые 15m/60m/240m сигналы создавали техническое MTF-покрытие, но не давали строгого критерия согласованности. Оператор мог увидеть 15m long как обычный кандидат, даже если 60m или 240m были против направления. Для intraday decision support это признано дефектом уровня high.

Исправлено:

- добавлен `app/mtf.py` — расчет MTF-сводки по символу;
- зафиксирована иерархия `15m entry / 60m bias / 240m regime-veto`;
- 60m и 240m больше не считаются самостоятельными entry-trigger: они получают класс `CONTEXT_ONLY` и не выводятся в operator queue как рекомендации на вход;
- 15m сигнал получает `NO_TRADE_CONFLICT`, если 60m или 240m против направления;
- `research_score` корректируется через `mtf_score`, `mtf_veto` и `higher_tf_conflict`;
- LLM payload теперь содержит MTF-контекст и причину MTF-решения;
- UI переработан в единый intraday cockpit: decision board, MTF matrix, trade ticket, красный чек-лист, очередь кандидатов и LLM/news-контекст вместо визуально несвязанных панелей;
- добавлены тесты `tests/test_mtf_consensus.py` на aligned intraday, conflict-veto и context-only поведение.

Принятое безопасное допущение: для intraday вход разрешается только по entry-TF. 60m и 240m могут усиливать, ослаблять или запрещать сигнал, но не являются точкой входа сами по себе.

## Дополнение ревизии 2026-04-26: фронтенд, UX и Bybit edge-cases

### Найденные проблемы

#### High

1. **Фронтенд не имел timeout для API-вызовов.** При зависшем backend, сетевом обрыве или подвисшем reverse-proxy оператор мог получить бесконечное ожидание без явного отказа. Исправлено: `api()` использует `AbortController` и возвращает понятную ошибку timeout.
2. **Операционные кнопки можно было запускать повторно во время уже выполняющейся операции.** Это могло параллельно инициировать загрузку рынка, пересчет сигналов или фоновые циклы из UI. Исправлено: введен `setBusy()` и single-flight guard в `runOperation()`.
3. **Bybit `retCode` парсился через прямой `int(ret_code)`.** Нестандартный gateway/body с нечисловым `retCode` приводил бы к `ValueError` вне нормального контракта `BybitAPIError`. Исправлено: `_parse_ret_code()` и корректная ошибка API без маскировки причины.
4. **Pagination instruments-info не имела защиты от повторяющегося cursor.** При дефекте API/gateway цикл мог стать бесконечным. Исправлено: `MAX_BYBIT_CURSOR_PAGES`, `seen_cursors`, валидация типа `result.list`.

#### Medium

1. **URL новостей вставлялся в `href` без whitelist схемы.** HTML escaping не запрещает `javascript:` как URL-схему. Исправлено: `safeExternalUrl()` разрешает только `http:` и `https:`.
2. **CSS-классы частично строились из данных backend.** Неожиданные значения могли ломать селекторы и визуальные состояния. Исправлено: `cssToken()` для токенов классов.
3. **Локальные numeric-библиотеки могли создавать избыточное число потоков.** Это особенно опасно для Windows/desktop research-стенда и тестового окружения. Исправлено: `sitecustomize.py` и `app.runtime` задают безопасные `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS`, не перезаписывая пользовательские значения.

### Что исправлено

- `frontend/styles.css`: переработан cockpit-дизайн, visual hierarchy, spacing, scroll-контейнеры, responsive behavior, busy-state.
- `frontend/app.js`: timeout API, single-flight UI operations, safe external links, class-token normalization.
- `frontend/index.html`: `type="button"`, `aria-live="polite"` для очереди кандидатов.
- `app/bybit_client.py`: устойчивый parse `retCode`, cursor-loop guard и лимит страниц.
- `app/runtime.py`, `sitecustomize.py`: безопасные лимиты потоков numeric runtime.

### Что добавлено в тесты

- `tests/test_frontend_decision_ui.py`: regression-тест timeout/busy/safe-link/button/aria инвариантов фронтенда.
- `tests/test_bybit_client_resilience.py`: тест нечислового `retCode` и тест повторяющегося Bybit cursor.
- `tests/test_runtime_environment.py`: тесты установки и сохранения numeric thread limits.

### Проверка этой доработки

Команды, выполненные в текущей среде:

```bash
node --check frontend/app.js
python -S -m compileall -q app tests run.py install.py sitecustomize.py
pytest -q -p no:cacheprovider tests/test_frontend_decision_ui.py
pytest -q -p no:cacheprovider tests/test_bybit_client_resilience.py
pytest -q -p no:cacheprovider tests/test_runtime_environment.py
```

Результаты целевых регрессий:

- `tests/test_frontend_decision_ui.py`: 7 passed;
- `tests/test_bybit_client_resilience.py`: 2 passed;
- `tests/test_runtime_environment.py`: 5 passed;
- `tests/smoke_test.py`: 1 passed;
- `tests/test_backtest_background.py`: 3 passed до зависания тестового runner на завершении процесса в контейнерной среде.

Ограничение проверки: в текущем контейнере импорт `pandas` может зависать на уровне окружения, поэтому полный `tests/test_core_safety.py` здесь не был надежно прогнан повторно. Код и targeted regression-тесты для внесенных изменений проверены отдельно; ранее существующий полный набор в проектной документации оставлен как baseline, но эта среда не позволяет честно подтвердить его полным прогоном после UX-доработки.
