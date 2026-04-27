# Frontend redesign notes — Bybit Research Lab

## Что было исправлено

1. Пересобрана структура `frontend/index.html` под операторский trading cockpit:
   - верхняя панель: система, биржа, актив, таймфрейм, update, API/DB/Signals/BT/LLM;
   - левая панель: параметры, операции, выбор символов, стратегия, очередь кандидатов;
   - центральная зона: главный сигнал, score, confidence/risk/RR meters, execution map, equity/backtest canvas, trade sheet;
   - правая панель: LLM verdict, MTF, risk/evidence, причины, новости, protocol;
   - нижняя зона: сырая таблица сигналов и debug-журнал.

2. Полностью переписан `frontend/styles.css`:
   - темная fintech/trading-тема;
   - стеклянные панели без кислотных цветов;
   - адаптивная 3/2/1-колоночная сетка;
   - sticky headers таблиц;
   - компактные карточки кандидатов;
   - равная высота основных рабочих панелей;
   - состояния `empty`, `loading`, `ok`, `warn`, `error`.

3. Улучшен `frontend/app.js` без изменения backend/API-контрактов:
   - добавлены безопасные `setText`-рендеры для новых topbar chips;
   - добавлены `priceFmt`, `renderDecisionMeters`, `renderExecutionMap`;
   - ключевые метрики теперь отображаются как meters: confidence, risk, risk/reward;
   - row-level подсветка направления в технической таблице;
   - сохранены существующие API: `/api/status`, `/api/research/rank`, `/api/signals/latest`, `/api/equity/latest`, `/api/news/latest`, `/api/llm/background/status`.

## Найденные frontend-проблемы

- В исходном UI главный торговый вывод визуально конкурировал с техническими блоками и операциями.
- В `index.html` не хватало явной верхней привязки к выбранной паре, таймфрейму и времени обновления.
- Визуальные компоненты существовали частично, но не были оформлены как единая система: SignalCard, RiskRewardCard, ConfidenceMeter, RiskMeter, IndicatorPanel, APIStatusIndicator, DebugConsole.
- CSS был функциональным, но требовал консолидации: много исторических полировок поверх базовой темы.
- JS в целом синтаксически корректен; критических ошибок синтаксиса не было, но часть DOM-обновлений была прямой и менее устойчива к будущим изменениям разметки.

## Остаточные backend/API-зависимости

- Реальный ценовой график зависит от подключения TradingView/lightweight-charts или отдельного candle endpoint.
- Поля `entry`, `stop_loss`, `take_profit`, `confidence`, `spread_pct`, `max_drawdown`, `mtf_*`, `llm_*` должны приходить в прежнем формате.
- LLM verdict отображается только после фонового цикла или ручного запуска `/api/llm/background/run-now`.
- Equity canvas по-прежнему показывает последнюю сохраненную equity-кривую или результат ручного бэктеста, а не меняется от простого выбора кандидата.

## Проверки

```text
node --check frontend/app.js — OK
python -S -m compileall -q app tests run.py install.py sitecustomize.py — OK
static frontend checks — OK: уникальные id, все JS DOM refs существуют, все button имеют type
```
