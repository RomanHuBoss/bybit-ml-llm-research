# Red-team аудит торгово-советующей системы Bybit — 2026-04-29

## Назначение проверки

Проверка выполнена как инженерная верификация советующей торговой СППР для крипторынка Bybit. Система рассматривается как advisory-only: она может выдавать рекомендации оператору (`NO_TRADE`, `WAIT`, `REVIEW_ENTRY`), но не должна отправлять ордера, подписывать private Bybit API-запросы или обходить ручное подтверждение.

## Краткая карта проекта

- `app/main.py` — FastAPI-приложение, статика frontend и запуск фоновых сервисов.
- `app/api.py` — HTTP API, агрегация сигналов, статусов, LLM/backtest/background endpoints.
- `app/bybit_client.py` — публичный Bybit V5 market-data клиент, свечи, funding, open interest, liquidity snapshot.
- `app/features.py` — сбор фичей из PostgreSQL и подготовка ML-матрицы.
- `app/strategies.py` — генерация торговых кандидатов, entry/SL/TP, confidence и rationale.
- `app/recommendation.py` — каноническая серверная классификация операторского действия.
- `app/mtf.py` — multi-timeframe consensus и veto.
- `app/operator_queue.py` — стабилизация очереди оператора и защита от конфликтующих сигналов.
- `app/safety.py` — свежесть свечей, валидность уровней и risk/reward.
- `app/research.py` — SQL-выборки для latest signals, LLM, backtest, rank/universe.
- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` — dark-mode trading cockpit.
- `tests/` — unit/static/integration-style проверки критичных контрактов.
- `sql/schema.sql`, `.env.example`, `requirements.txt`, `run.py` — запуск, схема БД и окружение.

## Состояние до исправлений

1. Regression-набор падал на противоречивом поведении unknown liquidity.
2. Отсутствующий liquidity snapshot и доказанный `is_eligible=false` могли смешиваться из-за одинаковых placeholder-значений `spread_pct=999`, `liquidity_score=0`.
3. Часть торговых признаков обрабатывалась через `x or default`, что ломало валидные нули: `bb_position=0`, `funding_rate=0`, `volume_z=0`, `ema20_50_gap=0`.
4. Frontend-risk meter трактовал неизвестный `spread_pct` как нулевой риск.
5. В тестах не было отдельного статического контракта, запрещающего private Bybit order-execution пути.
6. Документация не фиксировала явно новое разделение `unknown liquidity` и `known non-eligible liquidity`.

## Состояние после исправлений

- Все тесты проходят: `109 passed`.
- `node --check frontend/app.js` проходит.
- Python compile-проверка ключевых модулей проходит.
- Импорт ключевых backend-модулей проходит.
- Unknown liquidity теперь остается candidate-only/WAIT-состоянием и не становится `REVIEW_ENTRY`.
- Known `is_eligible=false` остается hard filter.
- Валидные нулевые торговые признаки больше не подменяются дефолтами.
- Frontend явно повышает risk meter при неизвестном spread.
- Добавлен static-тест на отсутствие Bybit private order execution markers.

## Найденные проблемы по критичности

### Critical

1. **Неопределенная ликвидность могла быть трактована противоречиво.**  
   Разные тесты и слои расходились: один сценарий ожидал расчет candidate, другой — блокировку, третий — ручной вход. Исправлено через явное `liquidity_state=unknown` и безопасный `WAIT`.

2. **Валидные нулевые признаки могли исчезать из торговой логики.**  
   Конструкции вида `_finite(..., default) or default` подменяли `0.0` дефолтом. Особенно опасный пример — `bb_position=0.0`, который означает цену у нижней полосы Bollinger, но превращался в нейтральное `0.5`.

3. **UI мог занижать риск при неизвестном spread.**  
   `num(s.spread_pct, 0)` делал отсутствующий spread равным нулю, то есть визуально безопасным.

### High

1. **Смешение placeholder missing snapshot и known non-eligible snapshot.**  
   Исправлено разделением `liquidity_state=unknown` в feature-layer и жесткой трактовкой `is_eligible=false` без этого маркера.

2. **Устаревший regression-тест требовал `REVIEW_ENTRY` при unknown liquidity.**  
   Исправлен на безопасный `WAIT` с предупреждениями `liquidity_unknown` и `spread_unknown`.

3. **Недостаточный тестовый контракт advisory-only.**  
   Добавлен тест, сканирующий backend/frontend на маркеры private Bybit order execution.

### Medium

1. **Недостаточные edge-case тесты числовых фичей.**  
   Добавлена проверка, что `bb_position=0.0` сохраняется и может участвовать в Bollinger/RSI reversion.

2. **Frontend-risk логика была частично не покрыта тестами.**  
   Добавлен static-тест на обработку unknown spread.

3. **Документация не фиксировала новое безопасное допущение на уровне feature-layer.**  
   README дополнен ревизией V16.

### Low

1. **Косметические несоответствия формулировок тестов.**  
   Уточнено имя теста unknown liquidity, чтобы оно соответствовало фактическому безопасному поведению.

## Исправления по направлениям

### Торгово-логические ошибки

- Добавлен `_finite_or()` в `app/strategies.py`, чтобы не терять валидные нули.
- Исправлены стратегии:
  - `donchian_breakout`;
  - `ema_pullback_trend`;
  - `bollinger_rsi_reversion`;
  - `volatility_squeeze_breakout`;
  - `funding_extreme_contrarian`;
  - `oi_trend_confirmation`;
  - `sentiment_extreme_reversal`;
  - `trend_continuation_setup`.
- Unknown liquidity теперь допускает расчет candidate только как warning-сценарий, но не как разрешение на вход.
- Known non-eligible liquidity остается hard block.

### Архитектурные ошибки

- Feature-layer теперь явно передает состояние `liquidity_state`.
- Strategy-layer больше не пытается выводить unknown/known только по placeholder-числам.
- Слой рекомендаций сохраняет роль единого сервера принятия операторского решения.

### Backend/Core ошибки

- Усилена защита от `None`/placeholder данных в liquidity features.
- Убрана опасная подмена нулевых значений дефолтами.
- Проверено отсутствие private order-execution markers в `app/` и `frontend/`.

### Frontend/UI/UX ошибки

- Risk meter больше не показывает неизвестный spread как безопасный.
- Добавлен `riskFromSpread(s)` с отдельным warning-весом для missing spread.
- Сохранены существующие dark-mode trading terminal структура, operator queue, decision board, MTF, checklist, alerts/debug panels.

### JavaScript-ошибки

- Исправлена логика `renderDecisionMeters`: unknown spread теперь повышает риск.
- `frontend/app.js` проходит `node --check`.

### Надежность и отказоустойчивость

- Неизвестный liquidity snapshot не скрывается молча и не превращается в разрешение на вход.
- Явная плохая ликвидность продолжает блокировать генерацию сигнала.
- Advisory-only контракт закреплен тестом.

### Тестовое покрытие

Добавлены/обновлены проверки:

- unknown liquidity → `WAIT`, warnings present, no `REVIEW_ENTRY`;
- missing liquidity snapshot with explicit `liquidity_state=unknown` → candidate can be calculated;
- known `is_eligible=false` → strategy returns `None`;
- `bb_position=0.0` is preserved in Bollinger/RSI logic;
- frontend unknown spread is not zero-risk;
- project does not contain Bybit private order-execution markers.

### Расхождения код ↔ документация

- README дополнен ревизией V16.
- Зафиксировано допущение: `liquidity_state=unknown` отличает отсутствие snapshot от доказанного `is_eligible=false`.
- Уточнено, что unknown liquidity не может быть основанием для `REVIEW_ENTRY`.

### Конфигурация и запуск

- `run.py doctor --no-venv` выполнен успешно.
- Чистая переустановка `requirements.txt` в sandbox не завершилась: pip-процесс был прерван ограничением среды. Проверки выполнены в доступном окружении, но перед staging/production запуском нужно создать чистый virtualenv и выполнить `pip install -r requirements.txt`.
- `.env` в среде отсутствовал, поэтому live DB/API startup не выполнялся.
- `.env.example` оставлен без изменения, так как текущие правки не требуют новых переменных окружения.

### Безопасность

- Подтверждено отсутствие private Bybit order execution markers в `app/` и `frontend/`.
- Система остается advisory-only.
- Отсутствующие market-data/liquidity данные трактуются консервативно.

## Результаты проверок

```text
pytest -q tests
109 passed in 2.42s

node --check frontend/app.js
OK

py_compile app/*.py run.py install.py sitecustomize.py
OK

import app.api, app.strategies, app.recommendation, app.features, app.bybit_client, app.operator_queue
OK

run.py doctor --no-venv
exit 0
```

## Что не удалось проверить в sandbox

- Реальный запуск FastAPI с PostgreSQL и живыми данными Bybit не выполнен: в среде нет `.env`, PostgreSQL-инстанса и внешних credentials.
- Чистая dependency-install проверка не завершена из-за ограничения sandbox на длительный pip subprocess; дополнительно глобальное окружение не является изолированным проектным venv.
- Браузерная проверка консоли frontend в настоящем Chromium/Firefox не выполнена: нет полноценного browser runtime в sandbox. Вместо этого выполнены `node --check`, static frontend tests и contract tests.
- Реальные rate-limit ответы Bybit не дергались live; проверены существующие resilience-тесты Bybit client.

## Оставшиеся риски

1. Требуется staging-прогон с реальной PostgreSQL БД, заполненными `candles`, `liquidity_snapshots`, `signals`, `backtest_runs`, `llm_evaluations`.
2. Требуется browser smoke/E2E прогон для фактической консоли, responsive layouts и пользовательских сценариев.
3. Для production-like режима нужны внешний мониторинг, alerting, backup/restore БД, метрики фоновых циклов и проверка долгих деградаций API.
4. Если в будущем будет добавлен private Bybit API, потребуется отдельный security gate и ручной approval workflow. Текущая система не содержит исполнения ордеров.

## Ключевые измененные файлы

- `app/features.py` — добавлен `liquidity_state` для разделения unknown snapshot и known non-eligible snapshot.
- `app/strategies.py` — исправлена обработка liquidity state и валидных нулевых признаков.
- `frontend/app.js` — unknown spread больше не считается нулевым UI-риском.
- `tests/test_advisory_futures_recommendations.py` — уточнены regression-сценарии liquidity и добавлен нулевой Bollinger edge-case.
- `tests/test_frontend_decision_ui.py` — добавлена проверка frontend-risk logic.
- `tests/test_advisory_only_contract.py` — добавлен static safety contract для advisory-only режима.
- `README.md` — добавлена ревизия V16.

## Новые файлы

- `docs/RED_TEAM_AUDIT_2026-04-29.md` — этот отчет.
- `tests/test_advisory_only_contract.py` — static test на отсутствие private order execution markers.

## Удаленные файлы

Файлы проекта не удалялись.
