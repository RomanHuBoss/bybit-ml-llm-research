# Red-team audit V25 — Signal Quality Contract / stuck-in-Research fix

Дата: 2026-05-01
Режим: советующая СППР, Bybit public market data, без автоматической отправки ордеров.

## Резюме

Проверка была выполнена по сценарию: система накопила большой объем свечей, но рабочее место оператора не выдает рекомендаций на ручную проверку входа и останавливается на Research-статусах.

Ключевая серверная причина найдена и исправлена: endpoint `/api/signals/latest`, который используется UI для очереди оператора, не подтягивал `strategy_quality` и последние backtest/model/LLM evidence. Поэтому даже approved-стратегии попадали в `classify_operator_action()` как строки без доказательной базы и безопасно классифицировались как `RESEARCH_CANDIDATE` или `WAIT`.

## Карта проекта

- `run.py`, `app/main.py` — запуск FastAPI, static frontend.
- `app/api.py` — основной API-контракт.
- `app/bybit_client.py` — публичный Bybit V5 REST, retry/backoff, market sync.
- `app/strategies.py` — генерация сигналов и стратегии.
- `app/mtf.py` — MTF consensus / veto.
- `app/recommendation.py` — каноническое операторское решение `NO_TRADE` / `WAIT` / `RESEARCH_CANDIDATE` / `REVIEW_ENTRY`.
- `app/operator_queue.py` — стабилизация очереди, один рынок = один операторский вердикт.
- `app/strategy_quality.py`, `app/strategy_quality_background.py` — Strategy Quality Gate.
- `app/research.py` — ранжирование исследовательских кандидатов.
- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` — dark-mode trading cockpit.
- `tests/` — regression/unit/static/integration проверки.

## Critical

### C-01. `/api/signals/latest` не видел Strategy Quality Gate

**До исправления**

`/api/signals/latest` выбирал свежие строки только из `signals` и не присоединял:

- `strategy_quality`;
- `backtest_runs`;
- `model_runs`;
- `liquidity_snapshots` как полноценный свежий evidence-контракт;
- `llm_evaluations`.

`classify_operator_action()` требует approved quality/backtest evidence для `REVIEW_ENTRY`. Без этих полей строка безопасно падала в `RESEARCH`, даже если отдельная витрина Strategy Lab уже показывала `APPROVED`.

**Исправление**

В `app/api.py` endpoint `/api/signals/latest` синхронизирован с research-контуром:

- добавлены CTE `latest_backtests`, `latest_models`, `latest_liq`, `latest_quality`, `latest_llm`;
- добавлены поля `quality_status`, `quality_score`, `evidence_grade`, `quality_reason`, `trades_count`, `profit_factor`, `max_drawdown`, `walk_forward_pass_rate`, `walk_forward_windows`, ML/LLM/liquidity evidence;
- добавлен SQL `research_score`;
- сохранен порядок safety-гейтов: freshness → MTF → recommendation classification → operator queue consolidation;
- перед запросом вызывается `ensure_strategy_quality_storage()` для мягкой миграционной устойчивости.

**Риск до исправления**: система могла никогда не показать `REVIEW_ENTRY` через UI, несмотря на накопленные свечи и approved-стратегии.

**Риск после исправления**: `REVIEW_ENTRY` появится только при свежем approved evidence и прохождении hard-veto; это намеренно консервативно.

## High

### H-01. Frontend не отличал обычный Research от поломки API-контракта quality

**Исправление**

В `frontend/app.js` добавлен контроль наличия `quality_status` и `quality_score`. Если backend снова не передаст эти поля, checklist покажет явную ошибку контракта Strategy Quality: `API не передал quality_status/quality_score`.

### H-02. Статические тесты не защищали `/api/signals/latest` от регрессии

**Исправление**

Добавлены тесты, подтверждающие, что operator endpoint реально содержит join на `strategy_quality`, backtest evidence, WF поля и `research_score`.

## Medium

### M-01. Документация не объясняла stuck-in-Research как отдельный диагностический сценарий

**Исправление**

README дополнен разделом V25: почему система могла застревать в Research и какие условия нужны для `REVIEW_ENTRY`.

### M-02. Legacy `APPROVED` без актуального walk-forward/backtest evidence

Сохранено безопасное поведение: такие строки не форсируются в сделку автоматически. Нужно обновить backtest/quality evidence через фоновый refresh. Это может уменьшать число входных рекомендаций, но защищает от ложных допусков.

## Low

### L-01. Cache-busting frontend CSS

Обновлена версия stylesheet в `index.html`, чтобы браузер не держал старый CSS.

## Проверки

Выполнено:

```bash
/usr/bin/python3 -m py_compile app/api.py app/recommendation.py app/strategy_quality.py app/operator_queue.py
node --check frontend/app.js
PYTHONPATH=/opt/pyvenv/lib/python3.13/site-packages:. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /opt/pyvenv/bin/python -S -m pytest -q
```

Результат полного pytest-набора: `139 passed in 2.49s`.

## Добавленные/обновленные тесты

- `tests/test_api_contract_static.py` — защита от повторного удаления quality/backtest joins из `/api/signals/latest`.
- `tests/test_recommendation_freshness_api.py` — endpoint может вернуть `REVIEW_ENTRY`, если свежая строка содержит approved quality/backtest/WF evidence.
- `tests/test_frontend_decision_ui.py` — frontend подсвечивает отсутствие Strategy Quality API-контракта как ошибку, а не как обычный Research.

## Оставшиеся риски и допущения

1. Без реальной PostgreSQL/Bybit среды невозможно доказать, что конкретная production-БД уже содержит свежие `strategy_quality` rows с актуальными WF/backtest metrics. Кодовой контракт исправлен; production-данные нужно обновить фоновым refresh/backtest.
2. Система остается советующей: `REVIEW_ENTRY` — только разрешение вынести сетап на ручную проверку, а не приказ на сделку.
3. Conservative gate может оставлять систему без входов при отсутствии свежей доказательной базы. Это ожидаемое безопасное поведение.
