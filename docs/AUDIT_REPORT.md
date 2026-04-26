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
- `python -m pytest -q`: `11 passed`.

Примечание: в контейнере pytest выдал только предупреждение о невозможности записи cache в .pytest_cache; на результат тестов это не повлияло.
