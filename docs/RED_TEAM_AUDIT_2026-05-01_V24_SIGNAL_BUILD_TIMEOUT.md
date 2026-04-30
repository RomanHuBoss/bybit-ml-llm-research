# V24 Signal Build Timeout Hotfix — 2026-05-01

## Проблема

UI выдавал ошибку:

```text
Signals built. API timeout after 45s: /api/signals/build
```

Причина: кнопка ручного построения сигналов использовала общий frontend-timeout 45 секунд. Для MTF-корзины `symbol × interval` это слишком мало: endpoint читает OHLCV, funding, open interest, sentiment/liquidity, считает индикаторы и сохраняет сигналы. Даже корректный тяжелый пересчет мог выглядеть как отказ системы.

## Исправления

1. `/api/signals/build` больше не обрабатывает `symbol × interval` строго последовательно.
   - Добавлен ограниченный `ThreadPoolExecutor` с `settings.signal_build_workers`.
   - В ответ добавлены `workers` и `jobs` для наблюдаемости.
   - Формат `result` сохранен обратно совместимым.

2. Frontend больше не использует дефолтные 45 секунд для ручного build.
   - Добавлен `signalBuildTimeoutMs()`.
   - Timeout масштабируется от количества `symbol × interval` job'ов.
   - UI показывает оператору, что идет тяжелый MTF-пересчет, а не короткий API-вызов.

3. Добавлены статические regression-тесты.
   - Проверка расширенного timeout в UI.
   - Проверка параллелизации `/api/signals/build` и метрик `workers/jobs`.

## Что это не меняет

- Автоматическая торговля не добавлена.
- Торговая логика сигналов не переписана.
- API-контракт `result` не сломан.
- Background-контуры backtest/LLM по-прежнему только запрашиваются после успешной вставки сигналов.

## Проверки в audit-среде

Выполнено:

```text
node --check frontend/app.js
python -S -m py_compile app/api.py tests/test_api_contract_static.py tests/test_frontend_decision_ui.py
manual_static_checks_ok
```

Дополнительно один новый API static test был запущен через pytest и прошел:

```text
tests/test_api_contract_static.py::test_signal_build_endpoint_is_parallelized_and_reports_job_count PASSED
```

Ограничение среды: полный `pytest` в текущей оболочке зависал на этапе импорта/завершения интерпретатора, поэтому для hotfix дополнительно выполнены прямые статические проверки и компиляция измененных Python-файлов.
