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
- `python -m pytest -q`: `24 passed`.

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
- `python -m pytest -q`: `24 passed`.

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
- `python -m pytest -q`: `24 passed`.

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
