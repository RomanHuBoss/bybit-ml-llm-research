# Финальная проверка и исправления: ML auto-train, консистентность, математика, GUI

Дата: 2026-04-28

## Ключевой вывод

В предыдущей версии ML-модель обучалась только вручную через `/api/ml/train`. Для системы, где symbol universe и сигналы обновляются автоматически, это было неконсистентно: новые или давно не обновлявшиеся `symbol+interval` могли попадать в research queue без актуального ML-доказательства. Это исправлено.

## Что изменено

### ML / econometrics

- Добавлен автоматический контроль моделей по каждой комбинации `category+symbol+interval+horizon`.
- Фоновый `signal-auto-refresher` теперь после обновления рынка и sentiment вызывает ML auto-train для всех market-ok `symbol+interval`.
- Модель переобучается, если:
  - отсутствует запись `model_runs`;
  - есть запись `model_runs`, но отсутствует локальный `.joblib` файл;
  - последняя модель старше `ML_AUTO_TRAIN_TTL_HOURS`.
- Добавлены настройки:
  - `ML_AUTO_TRAIN_ENABLED=true`
  - `ML_AUTO_TRAIN_TTL_HOURS=24`
  - `ML_AUTO_TRAIN_HORIZON_BARS=12`
  - `ML_AUTO_TRAIN_MAX_MODELS_PER_CYCLE=2`
  - `ML_AUTO_TRAIN_FAILURE_COOLDOWN_HOURS=6`
  - `ML_PROBABILITY_IN_SIGNALS_ENABLED=true`
- `signals.ml_probability` теперь заполняется направленной вероятностью:
  - для `long`: `P(up)`;
  - для `short`: `1 - P(up)`.
- `research/rank` больше не усиливает score устаревшими ML-метриками: `model_runs` учитываются только в пределах TTL.

### Runtime / import safety

- `app.api` больше не импортирует FastAPI на уровне обычного импорта модуля. Для тестов, CLI и диагностики endpoint-функции доступны без ASGI-инициализации.
- Для web-сервера `app.main` материализует настоящий `APIRouter` через deferred router.
- `app.serialization` больше не импортирует pandas внутри общей проверки каждого скаляра. Это устраняет лишний тяжелый импорт аналитического стека в LLM/API-сериализации.

### GUI / API visibility

- `/api/status` показывает параметры ML auto-train.
- `/api/signals/background/status` возвращает сводку последнего ML auto-train цикла.
- Ручные кнопки запуска ML из основного frontend удалены: оператор видит ML-доказательства, но не обязан запускать обучение вручную.
- Frontend использует `ml_probability`, `roc_auc`, `precision_score`, `recall_score`; backend поддерживает эти поля автоматически.

### Тесты

- Обновлены regression-тесты под frozen Settings через `dataclasses.replace`.
- Обновлен тест MTF queue: bar_time теперь строится относительно текущего времени, чтобы тест не становился ложностарым.
- Обновлен тест фонового signal pipeline: проверяется, что ML auto-train вызывается между sentiment sync и построением сигналов.

## Проверки

В контейнере выполнено:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=/opt/pyvenv/lib/python3.13/site-packages:. \
python -S -m pytest -q
# 75 passed

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
PYTHONPATH=/opt/pyvenv/lib/python3.13/site-packages:. \
python -S -m compileall -q app tests install.py run.py sitecustomize.py

node --check frontend/app.js
```

Ограничение контейнера: обычный `python` в этой среде печатает результат, но не завершает процесс после site initialization. Поэтому Python-проверки выполнялись через `python -S` с явным `PYTHONPATH` и лимитами BLAS-потоков. Это ограничение среды, а не кода проекта; оно отдельно подтверждено простым `python -c 'print(1)'`.

## Итог

Система больше не требует ручного ML-обучения по каждому символу в штатном контуре. Ручные ML-кнопки из основного интерфейса удалены; API `/api/ml/train` и `/api/ml/predict/latest` оставлены как диагностический/аварийный инструмент.

## Дополнительная правка по UX и нагрузке VM

После контрольного вопроса по интерфейсу и частоте ML-добучения внесена отдельная правка:

- Ручные кнопки `Обучить ML` и `ML‑прогноз` удалены из основной панели операций frontend.
- JS-обработчики этих кнопок также удалены, чтобы UI не содержал мертвых элементов.
- API `/api/ml/train` и `/api/ml/predict/latest` оставлены для аварийной диагностики и внешней автоматизации, но операторский workflow больше на них не опирается.
- Дефолт `ML_AUTO_TRAIN_MAX_MODELS_PER_CYCLE` снижен с `8` до `2`, чтобы cold-start не перегружал слабую VM.
- Добавлен `ML_AUTO_TRAIN_FAILURE_COOLDOWN_HOURS=6`: если обучение конкретного `symbol+TF+horizon` падает, например из-за недостатка истории или одного класса target, эта же комбинация не будет бесполезно переобучаться каждые 5 минут.
- `app.ml` дополнительно разгружен: `sklearn/joblib` и pandas-heavy feature functions импортируются лениво только при реальном train/predict, а статический список ML-признаков вынесен в `app/feature_schema.py`.

Дополнительные проверки текущей правки:

```bash
node --check frontend/app.js
PYTHONPATH=/opt/pyvenv/lib/python3.13/site-packages:. \
python -S -m compileall -q app tests install.py run.py sitecustomize.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=/opt/pyvenv/lib/python3.13/site-packages:. \
python -S -m pytest -q tests/test_signal_background.py tests/test_ml_autotrain_cooldown.py tests/test_frontend_decision_ui.py
# 17 passed
```

Полный pytest в текущем контейнере не был повторно завершен из-за зависания импорта `pandas`/`sklearn` в самой среде выполнения. Проверки, не требующие этих тяжелых импортов, завершились успешно; кодовые изменения дополнительно покрыты compileall и `node --check`.
