# Frontend Redesign V9 — Bybit Research Lab

## Краткий аудит

Текущий frontend был статическим FastAPI-интерфейсом с точками входа `frontend/index.html`, `frontend/styles.css`, `frontend/app.js`. Бизнес-логика API уже была завязана на существующие endpoints `/api/status`, `/api/research/rank`, `/api/signals/latest`, `/api/equity/latest`, `/api/news/latest`, `/api/llm/*`, `/api/backtest/*`, `/api/ml/*`.

Главные проблемы, которые исправлены в V9:

1. Таблица сырых сигналов рендерила 14 `td` при 13 заголовках: после колонки TF повторно выводился `interval`, из-за чего колонки смещались.
2. Таблица не имела интерактивной сортировки по ключевым колонкам.
3. Основная зона недостаточно явно показывала текущую цену/entry, ожидаемое движение, направление и микроструктурные индикаторы.
4. CSS был приведен к единому dark-mode trading-terminal стилю: плотная сетка, glass panels, строгая иерархия цвета, адаптивность.
5. Добавлены защитные обработчики `window.error` и `unhandledrejection`, чтобы JS/API-ошибки попадали в видимый status/toast и debug-log, а не оставались только в консоли.

## Новая структура экрана

- Верхняя панель: система, Bybit, выбранная пара, таймфрейм, last update, LIVE OFF, статусы DB/Signals/BT/LLM, refresh.
- Левая панель: очередь 15m-кандидатов, фильтры, symbols/category/MTF/universe/strategy, быстрые переключатели индикаторов, ручные операции.
- Центр: главный SignalCard, PriceCard/KPI, Confidence/Risk/RR meters, execution map, equity canvas, trade ticket.
- Правая панель: LLM verdict, MTF matrix, microstructure indicators, Risk & evidence, factors, LLM, news, operator protocol, market sentiment.
- Низ: technical details, sortable raw signal table, debug console.

## Измененные файлы

- `frontend/index.html` — семантическая структура интерфейса, новые KPI, microstructure panel, sortable table headers.
- `frontend/styles.css` — полностью переписанная темная тема, адаптивная сетка, компоненты, таблицы, состояния.
- `frontend/app.js` — сохранены существующие API и бизнес-логика; добавлены headline/microstructure updates, sortable raw table, error capture; исправлен row/column mismatch.

## Сохраненные API-контракты

Формат backend/API не менялся. UI продолжает использовать существующие endpoints и поля сигналов. Если backend не отдаёт отдельные поля `open_interest`, `last_price`, `close`, funding или liquidation, интерфейс деградирует безопасно и показывает `—` или fallback из `entry/turnover/sentiment`.

## Риски/зависимости

- Canvas сейчас строит equity curve/backtest, а не полноценный свечной график. Для полноценного графика нужен отдельный endpoint с OHLCV либо подключение lightweight-charts/TradingView widget.
- Funding/open interest/liquidations зависят от того, какие поля backend реально добавит в `/api/research/rank` или `/api/signals/latest`.
- LLM verdict зависит от фонового `/api/llm/evaluations/latest`; ручной endpoint `/api/llm/brief` намеренно не используется.
- LIVE OFF оставлен как защитный режим: frontend не отправляет торговые ордера.
