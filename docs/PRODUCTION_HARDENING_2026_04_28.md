# Production hardening audit — 2026-04-28

## 1. Карта проекта

### Назначение

Проект — советующая СППР для крипторынка Bybit. Он собирает публичные рыночные данные, рассчитывает признаки и стратегии, ранжирует сетапы, добавляет ML/LLM/backtest evidence и показывает оператору рекомендации. Проект не содержит live-order execution и не должен автоматически торговать.

### Технологии

- Backend: Python, FastAPI, PostgreSQL, psycopg2, pandas/numpy, sklearn/joblib.
- Биржа: Bybit V5 public REST.
- ML: sklearn-классификация направления на horizon bars, локальные `.joblib`-артефакты.
- LLM: Ollama-compatible HTTP endpoint.
- Frontend: Vanilla HTML/CSS/JavaScript, dark-mode trading terminal.
- Тесты: pytest + статические frontend-contract тесты.

### Ключевые каталоги

- `app/api.py` — FastAPI endpoints и lightweight route recorder для import-time диагностики.
- `app/bybit_client.py` — Bybit public REST client, retry/backoff, валидация формата ответов.
- `app/strategies.py` — расчет торговых стратегий, risk levels, signal validation, сохранение сигналов.
- `app/research.py` — ranking queue, MTF-фильтрация, join с backtest/ML/liquidity/LLM.
- `app/recommendation.py` — новая каноническая классификация операторского решения.
- `app/mtf.py` — multi-timeframe consensus.
- `app/safety.py` — freshness/risk-reward safety annotations.
- `app/signal_background.py` — фоновый цикл universe/market/sentiment/signals/backtest/LLM/ML auto-train.
- `app/ml.py` — обучение и inference ML-моделей.
- `frontend/index.html`, `frontend/styles.css`, `frontend/app.js` — trading terminal UI.
- `sql/schema.sql` — схема PostgreSQL.
- `tests/` — regression/safety/frontend/static tests.

### Точки входа

- `run.py` — запуск/проверка проекта.
- `install.py` — установка окружения.
- `app/main.py` — FastAPI application.
- `frontend/index.html` — основной UI.

## 2. Главный дефект, объясняющий “вечное наблюдение”

До этой ревизии `research/rank` и `/api/signals/latest` возвращали строки сигналов, но не возвращали каноническое решение для оператора. Frontend сам собирал checklist и мог трактовать отсутствие optional-evidence — ML/backtest/LLM — как причину оставить актив в `НАБЛЮДАТЬ`. На практике это создавало режим, где даже сильный свежий сетап мог не переходить в actionable review, пока все дополнительные слои не завершены.

Исправление: добавлен backend-модуль `app.recommendation`, который явно классифицирует строку в одно из трех состояний:

- `NO_TRADE` / `НЕТ ВХОДА` — сработал hard-veto;
- `WAIT` / `НАБЛЮДАТЬ` — критического veto нет, но совокупная доказательность недостаточна;
- `REVIEW_ENTRY` / `РУЧНАЯ ПРОВЕРКА ВХОДА` — сетап можно вынести оператору на ручную проверку.

Важно: `REVIEW_ENTRY` не является командой купить/продать и не создает ордер. Это только операторский допуск к ручной проверке.

## 3. Исправленная торговая логика

### Hard-veto

Hard-veto теперь блокирует вход при следующих состояниях:

- нет направления LONG/SHORT;
- данные устарели, нет `bar_time`, свеча не закрыта;
- MTF конфликтует со старшими таймфреймами;
- liquidity universe явно пометил инструмент как not eligible;
- spread шире лимита;
- entry/SL/TP невалидны;
- risk/reward ниже защитного минимума;
- confidence ниже входного минимума;
- бэктест отрицательный при достаточном числе сделок.

### Evidence notes

ML, LLM и backtest больше не являются безусловной причиной вечного `НАБЛЮДАТЬ`, если они еще не готовы. Они понижают `operator_score` и выводятся как evidence notes для оператора.

### Risk/Reward

`risk_reward` теперь рассчитывается на backend и возвращается в API-строку. Если entry/SL/TP не позволяют оценить риск, строка получает hard-veto.

### Fresh closed candle

`build_latest_signals()` больше не зависит только от последней строки dataframe. Он ищет последнюю свежую закрытую свечу в хвосте. Это защищает систему от ситуации, когда одна текущая/битая незакрытая свеча в конце БД обнуляет все рекомендации по паре.

## 4. ML auto-train и нагрузка на VM

Настройки по умолчанию изменены на более щадящие:

```env
ML_AUTO_TRAIN_TTL_HOURS=168
ML_AUTO_TRAIN_MAX_MODELS_PER_CYCLE=1
```

Это означает, что модели не переобучаются ежедневно по всем `symbol+TF`, а обновляются постепенно и не чаще недельного TTL, если артефакт существует. Отсутствующая модель по-прежнему будет обучаться автоматически, но очередь растягивается во времени, чтобы не перегружать CPU/RAM слабой VM.

## 5. Backend/core исправления

- Добавлен `app/recommendation.py` как единый серверный контракт операторского решения.
- `/api/signals/latest` и `/api/research/rank` возвращают `operator_action`, `operator_label`, `operator_score`, `operator_hard_reasons`, `operator_warnings`, `operator_evidence_notes`, `risk_reward`.
- `app/config.py` больше не зависит от `python-dotenv` на import-time: добавлен минимальный безопасный `.env` loader. Это снижает риск зависания приложения до старта API.
- `app/strategies.py` ищет последнюю свежую закрытую свечу и не строит рекомендации по устаревшему рынку.
- Сохранено отсутствие автоматической отправки ордеров.

## 6. Frontend/UI/UX исправления

- Frontend использует backend-классификацию как каноническую, а не пересчитывает критичное решение самостоятельно.
- `НЕТ ВХОДА`, `НАБЛЮДАТЬ`, `РУЧНАЯ ПРОВЕРКА ВХОДА` отображаются как разные operator states.
- Пустая очередь теперь объясняет, что рынок мог обновиться, но ни одна стратегия не дала entry-сетап на свежей закрытой свече. Это отличает штатное WAIT-состояние от ML-ошибки.
- Добавлены CSS hardening-правки для topbar, cockpit grid, очереди кандидатов, таблиц и узких экранов.
- Уточнены цвета и бейджи для review/watch/reject.
- Исправлены regression-тесты frontend-контракта под новую терминологию `РУЧНАЯ ПРОВЕРКА ВХОДА`.

## 7. Новые и обновленные тесты

Добавлены:

- `tests/test_operator_recommendation.py` — проверяет:
  - сильный сетап допускается к ручной проверке даже без готовых ML/backtest evidence;
  - MTF-конфликт блокирует вход;
  - отрицательный бэктест при достаточном числе сделок блокирует вход;
  - умеренный confidence оставляет сетап в WAIT.
- `tests/test_latest_closed_signal_bar.py` — проверяет:
  - незакрытый tail-bar не обнуляет предыдущий свежий закрытый бар;
  - устаревший рынок не допускается к сигналу.

Обновлены:

- `tests/test_frontend_decision_ui.py` — frontend-contract теперь ожидает `РУЧНАЯ ПРОВЕРКА ВХОДА`, а не старую двусмысленную формулировку.

## 8. Выполненные проверки

В текущем контейнере выполнены:

```bash
/opt/pyvenv/bin/python -S -m compileall -q app tests install.py run.py sitecustomize.py
node --check frontend/app.js
```

Результат: успешно.

Дополнительно вручную выполнены содержательные тесты без pytest runner:

```bash
# tests/test_operator_recommendation.py
# результат: 4 теста пройдены

# tests/test_latest_closed_signal_bar.py
# результат: 2 теста пройдены

# tests/test_frontend_decision_ui.py
# результат: 13 статических frontend-contract тестов пройдены
```

Ограничение среды: полноценный `pytest`/`run.py check` в этом контейнере зависает на окружении импорта/pytest runner. Поэтому итоговая проверка выполнена через `python -S compileall`, `node --check` и прямой запуск ключевых тестовых функций. Live PostgreSQL, Bybit и Ollama в контейнере не поднимались.

## 9. Оставшиеся риски

- Проект остается советующей СППР, а не системой исполнения. EXIT-рекомендации без учета реального состояния позиции являются неполными; для полноценного EXIT нужен отдельный position-state/account-sync модуль.
- Backtest баровый и не моделирует очередь заявок, частичные исполнения, liquidation engine и order-book slippage.
- LLM/sentiment являются evidence-layer и не должны использоваться как самостоятельный торговый триггер.
- Для live-production эксплуатации нужен мониторинг PostgreSQL, freshness SLA, process supervisor, резервное копирование и наблюдаемость фоновых задач.
- UI не проверялся в реальном браузере с DevTools из-за ограничений контейнера; выполнена статическая JS/CSS/HTML-проверка и `node --check`.

## 10. Принятые допущения

- Отсутствующий ML/backtest — это не hard-veto, а evidence-gap. Иначе новые пары будут бесконечно сидеть в `НАБЛЮДАТЬ` до завершения всех вспомогательных контуров.
- `REVIEW_ENTRY` означает только ручную проверку оператором, а не разрешение на автоматическую сделку.
- Default ML retraining должен быть щадящим для VM: недельный TTL и 1 модель за цикл безопаснее, чем ежедневное массовое переобучение.
- Если данных нет или они устарели, состояние по умолчанию — запрет входа.
