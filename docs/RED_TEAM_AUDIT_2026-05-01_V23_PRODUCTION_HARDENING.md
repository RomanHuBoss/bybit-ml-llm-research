# Red-team audit V23 — production hardening СППР Bybit

Дата: 2026-05-01

## Резюме до исправлений

Система уже содержала базовую advisory-only архитектуру, MTF-filter, Strategy Lab, background backtest/LLM и современный dark UI. Однако после red-team проверки выявлены дефекты, которые объясняют недоверие оператора к рекомендациям:

- runtime-DDL Strategy Lab мог падать на fresh PostgreSQL из-за двойного `diagnostics JSONB`;
- legacy `APPROVED` мог оставаться допустимым без walk-forward evidence;
- устаревший backtest evidence не блокировал ручную проверку входа;
- frontend показывал score и quality, но не выделял отдельный trust/risk gate как главный операторский фильтр;
- слабый/малый backtest мог выглядеть как «плохая рекомендация», а не как нормальный запрет/исследовательский статус.

## Резюме после исправлений

Введен V23 trust gate:

- `REVIEW_ENTRY` не выдается только по confidence; теперь нужен достаточный серверный score;
- сохраненный `APPROVED` переоценивается с учетом свежести evidence и walk-forward;
- stale strategy evidence переводит рекомендацию в `NO_TRADE`;
- добавлены `operator_risk_score`, `operator_risk_grade`, `operator_trust_status`;
- frontend показывает Trust/Risk в карточке, чек-листе, очереди и raw-таблице;
- добавлены regression-тесты на stale evidence, WF-required approval и schema DDL.

## Найденные проблемы по критичности

### Critical

1. **Fresh DB initialization risk**: в `app/strategy_quality.py` runtime-DDL дважды объявлял `diagnostics JSONB`. На чистой БД это могло ломать создание таблицы `strategy_quality`.
2. **Legacy approval bypass**: `effective_strategy_quality()` принимал явный `quality_status=APPROVED` без повторной проверки новых требований к evidence.

### High

1. **APPROVED без walk-forward**: стратегия могла стать `REVIEW_ENTRY` по backtest-метрикам без rolling/walk-forward устойчивости.
2. **Stale evidence**: старый backtest сохранял статус допуска, хотя рынок и режимы могли измениться.
3. **Confidence bypass**: `REVIEW_ENTRY` мог появляться при высоком confidence даже при недостаточном итоговом score.

### Medium

1. **UI не показывал отдельный trust gate**: оператор видел score/quality, но не получал компактный статус «допущено / заблокировано / research only».
2. **Слабый backtest воспринимался как ошибка системы**: логика была безопасной, но объяснение было недостаточно явным.
3. **Raw table не содержала trust/risk**: сложно было сортировать и быстро выявлять причины запрета.

### Low

1. README не описывал новые жесткие требования V23 к актуальности evidence.
2. `.env.example` не содержал параметров fresh/WF trust gate.

## Что исправлено

- `app/strategy_quality.py`
  - удален дублирующий `diagnostics JSONB`;
  - добавлена проверка stale backtest через `STRATEGY_QUALITY_MAX_AGE_DAYS`;
  - добавлен статус `STALE` в фактическую оценку legacy rows;
  - добавлено требование `REQUIRE_WALK_FORWARD_FOR_APPROVAL`;
  - добавлены проверки expectancy и recent 30d return;
  - `effective_strategy_quality()` больше не доверяет старому `APPROVED`, если новая оценка его не подтверждает.

- `app/recommendation.py`
  - `STALE` evidence становится hard veto;
  - удален обход score-гейта через один высокий confidence;
  - добавлены `operator_risk_score`, `operator_risk_grade`, `operator_trust_status`.

- `app/config.py`, `.env.example`, `app/api.py`
  - добавлены и валидируются параметры V23 trust gate;
  - `/api/status` возвращает новые параметры Strategy Quality.

- `frontend/app.js`, `frontend/index.html`, `frontend/styles.css`
  - карточка сделки показывает `Risk score` и `Trust gate`;
  - чек-лист содержит отдельный пункт `Trust gate`;
  - очередь показывает risk в компактной строке;
  - raw table получила колонку `Trust/Risk` и сортировку;
  - frontend продолжает использовать серверную классификацию как каноническую.

- `tests/`
  - добавлены и обновлены тесты для V23 gate.

## Торгово-логические ошибки

- `APPROVED` без walk-forward больше не является достаточным основанием для `REVIEW_ENTRY`.
- Устаревший quality/backtest evidence теперь блокирует вход.
- Высокий confidence больше не может единолично протащить рекомендацию в ручной вход.
- Слабые стратегии остаются `RESEARCH_CANDIDATE`/`WAIT`, а не маскируются под торговую рекомендацию.

## Архитектурные ошибки

- Runtime-DDL должен быть синхронизирован со схемой и миграцией. Дублирование `diagnostics JSONB` исправлено.
- Серверная классификация остается канонической; frontend только визуализирует и деградирует безопасно.

## Backend/core ошибки

- Добавлена переоценка legacy quality rows.
- Добавлена защита от stale evidence.
- Добавлены новые поля risk/trust в операторский контракт без ломки старого API.

## Frontend/UI/UX ошибки

- Trust/risk теперь виден за 3–5 секунд в главной карточке и таблице.
- Пустой Trading Desk интерпретируется как штатный safety-gate, а не как «нет данных».
- Raw table получила дополнительную колонку для сортировки по operator risk.

## JavaScript-ошибки

- `node --check frontend/app.js` проходит.
- Изменения выполнены без смены API-контракта и без небезопасного `eval`.

## Надежность и отказоустойчивость

- Fresh DB risk устранен на уровне runtime-DDL.
- Legacy `APPROVED` не является вечным состоянием.
- Новые параметры вынесены в `.env.example` и `/api/status`.

## Тестовое покрытие

Добавлены/обновлены:

- `tests/test_strategy_quality_schema.py` — single `diagnostics JSONB` в runtime schema;
- `tests/test_strategy_lab_v20.py` — `REQUIRE_WALK_FORWARD_FOR_APPROVAL`, stale backtest;
- `tests/test_operator_recommendation.py` — stale `APPROVED` блокируется как `NO_TRADE`.

В текущей среде успешно выполнен быстрый набор из 17 V23-тестов и `node --check frontend/app.js`. Полный pandas-зависимый набор в этой контейнерной среде не удалось корректно завершить из-за зависания импорта `pandas`; это ограничение среды, а не подтвержденный дефект проекта.

## Оставшиеся риски

1. Нужен production/staging прогон с реальной PostgreSQL и актуальными Bybit данными.
2. После обновления надо запустить Strategy Quality refresh, иначе старые rows будут переоценены только при чтении, но не все агрегаты сразу обновятся в БД.
3. Стратегии, которые не проходят WF, не должны восприниматься как «сломанные»: это безопасное `NO REVIEW`, пока не будет достаточной доказательной базы.
4. Текущая система остается советующей. Автоматическое исполнение ордеров по-прежнему отсутствует и не добавлялось.
