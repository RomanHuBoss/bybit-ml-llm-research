# Audit Report V44 — Bybit Futures Advisory Research Lab

## Назначение итерации

Итерация V44 была выполнена как защитная инженерная доработка советующей торговой СППР. Главный фокус: не допускать искажения качества рекомендаций из-за поврежденных рыночных данных, сделать статистику рекомендаций более объяснимой для оператора и убрать обнаруженный JavaScript-дефект без изменения публичного advisory-контракта.

## Карта проекта

- `frontend/` — vanilla HTML/CSS/JS trading cockpit, dark-mode dashboard, operator queue, cards, MTF/evidence panels, sortable raw signal table.
- `app/api.py` — FastAPI-compatible endpoint-функции, recommendation contract, system warnings, quality endpoints.
- `app/bybit_client.py` — публичный Bybit V5 REST ingestion с retry/backoff.
- `app/strategies.py`, `app/recommendation.py`, `app/operator_queue.py`, `app/safety.py`, `app/mtf.py` — расчет стратегических сигналов, MTF/veto, финальный операторский вердикт.
- `app/recommendation_outcomes.py` — оценка исхода рекомендаций, SL/TP/expiry/MFE/MAE/realized R.
- `sql/schema.sql`, `sql/migrations/` — PostgreSQL schema и идемпотентные миграции.
- `tests/` — pytest regression/unit/static/integration tests.
- `run.py` — единая CLI-точка запуска приложения, миграций и проверок.

## Состояние до исправлений

Проект уже имел зрелую advisory-only архитектуру: публичные market-data источники, явные `NO_TRADE`/`WAIT`/`REVIEW_ENTRY` состояния, MTF-veto, quality gate и 226 проходящих тестов. При этом аудит выявил зоны риска, которые могли искажать операторское восприятие качества рекомендаций:

- outcome evaluation мог получать невалидные OHLC-бары и не маркировать их как отдельный data-quality risk;
- quality endpoint не давал оператору полного сегментного разреза по timeframe/direction/signal type;
- frontend не показывал качество похожих рекомендаций как компактный decision-support блок;
- в `frontend/app.js` был дублированный unreachable `return`;
- integrity/warnings слой не имел V44-представлений для market-data/outcome diagnostics.

## Найденные проблемы по критичности

### Critical

- Автоматической торговли или private order execution в проекте не обнаружено. Критичного live-execution дефекта не найдено.

### High

- Невалидные OHLC-свечи могли попасть в outcome evaluator и исказить MFE/MAE/SL/TP интерпретацию.
- Качество рекомендации было недостаточно сегментировано: оператор не мог быстро отделить слабость конкретного направления/TF/типа сигнала от общего качества стратегии.
- `/api/system/warnings` не смотрел на самый новый integrity audit view V44.

### Medium

- UI не имел компактной панели quality segments рядом с торговым контекстом; часть evidence была доступна, но не в удобном для 3–5 секундного решения виде.
- PostgreSQL constraints сильнее защищали recommendation contract, чем raw market/liquidity/outcome integrity.

### Low

- В `cleanLlmText()` был дублированный unreachable `return`, не ломавший runtime, но ухудшавший поддерживаемость и статическую чистоту JS.

## Исправления

### Trading / outcome logic

- Добавлена `_valid_candle_range()` в `app/recommendation_outcomes.py`.
- Невалидные свечи теперь пропускаются и не участвуют в расчете экстремумов, SL/TP и realized R.
- Результаты с пропущенными свечами получают `notes.data_quality_issue=true`, `notes.invalid_candles_skipped`, `notes.valid_bars_evaluated`.
- Если после фильтрации нет ни одного валидного бара, outcome получает явную причину `no_valid_market_bars`, а не выглядит как обычный expiry/open case.

### API / backend

- `/api/recommendations/quality` расширен сегментами `by_timeframe`, `by_direction`, `by_signal_type`.
- Все сегменты quality response получили `sample_confidence` и `sample_warning`.
- Добавлен `operator_guidance`, объясняющий, как интерпретировать статистическую слабость выборки.
- Recommendation metadata теперь сообщает о доступных quality segments и audit view V44.
- `/api/system/warnings` сначала использует `v_recommendation_integrity_audit_v44`, затем fallback на V43/V40.

### PostgreSQL

Добавлена миграция `20260505_v44_market_data_integrity_and_quality_segments.sql`:

- `ck_candles_ohlc_integrity_v44`;
- `ck_liquidity_snapshot_prices_v44`;
- `ck_recommendation_outcomes_metrics_v44`;
- integrity scan индексы;
- `v_recommendation_quality_segments_v44`;
- `v_recommendation_integrity_audit_v44`;
- `v_recommendation_contract_v44`.

CHECK-ограничения созданы как `NOT VALID`, чтобы не ломать существующие БД с историческими загрязненными строками. Для production после очистки данных нужно выполнить `VALIDATE CONSTRAINT`.

### Frontend / UI / UX

- Добавлена панель `Recommendation quality segments` в правую аналитическую часть.
- Панель показывает quality по рынкам, TF, направлениям, confidence buckets и signal types.
- Реализованы состояния loading/error/empty для quality panel.
- Frontend продолжает только отображать проверенные backend-данные и не рассчитывает торговые рекомендации самостоятельно.
- Исправлен дублированный unreachable `return` в `cleanLlmText()`.

### Документация

- README обновлен разделом `Market Data Integrity and Quality Segments V44`.
- Уточнено, что публичный `contract_version` остается `recommendation_v40`, а V44 является совместимым расширением integrity/quality/UX.
- Добавлен этот audit report.

## Измененные файлы

- `app/api.py` — расширение quality endpoint, V44 metadata, V44 warnings fallback.
- `app/recommendation_outcomes.py` — фильтрация невалидных OHLC и notes data quality.
- `frontend/app.js` — quality panel state/fetch/render, исправление unreachable code.
- `frontend/index.html` — новый блок quality segments.
- `frontend/styles.css` — стили quality segments panel.
- `sql/schema.sql` — синхронизация fresh schema с V44 migration.
- `sql/migrations/20260505_v44_market_data_integrity_and_quality_segments.sql` — новая миграция.
- `tests/test_v44_market_data_and_quality_segments.py` — новые regression tests.
- `README.md` — документация V44.
- `docs/AUDIT_REPORT_V44.md` — отчет аудита.

Удаленных файлов нет.

## Тесты

Добавлены regression-тесты на:

- пропуск невалидных OHLC в outcome evaluation;
- явную маркировку `data_quality_issue` при отсутствии валидных баров;
- наличие новых quality segments и sample-context в API source;
- наличие quality panel и отсутствие дублированного unreachable `return` во frontend;
- наличие V44 migration/schema audit artifacts.

Контрольный прогон в sandbox:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests
# 231 passed in 3.31s

node --check frontend/app.js
# OK

python -m py_compile app/*.py
# OK
```

`python run.py check` был также проверен, но в данной sandbox-среде родительский процесс иногда не возвращал управление после subprocess-проверок до timeout. Поэтому как формальный passed засчитан прямой эквивалентный pytest-прогон с теми же защитными env-флагами.

## Проверки, которые не выполнены в sandbox

- Реальное применение миграции к живой PostgreSQL БД не выполнялось: в sandbox нет подключенной production/staging БД.
- Реальный Bybit network ingestion не прогонялся: проверялась статическая и unit/integration-логика проекта без внешней сети.
- Браузерный E2E с DevTools console не выполнялся: выполнен `node --check` и статические frontend regression tests.

## Оставшиеся риски

- До `VALIDATE CONSTRAINT` старые загрязненные строки в production БД могут сохраняться; нужен отдельный data-cleanup runbook.
- OHLC outcome model остается консервативной approximation; точный intrabar path требует lower-TF/tick данных.
- Quality statistics не является вероятностью прибыли текущей сделки; UI и README это явно фиксируют.
- Для production нужны отдельные мониторинг, алертинг, backup/recovery PostgreSQL и staging-прогон миграций.

## Принятые допущения

- Совместимость публичного API важнее смены версии контракта: `recommendation_v40` сохранен.
- При поврежденной свече безопаснее исключить бар из outcome evaluation и показать data-quality warning, чем молча считать по нему результат.
- Слабая статистическая выборка должна снижать уверенность оператора, но не должна автоматически превращать все сигналы в бессодержательное `NO_TRADE` без объяснения.
