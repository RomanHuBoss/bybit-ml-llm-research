# Финальный аудит advisory futures СППР — 2026-04-29

## Контекст

Проверка выполнена как red-team ревизия советующей торговой системы Bybit. Цель ревизии — убрать двусмысленность вокруг автоматической торговли и обеспечить практичную выдачу фьючерсных рекомендаций `LONG` / `SHORT` / `WAIT` / `EXIT` в формате, пригодном для оператора: `entry`, `stop_loss`, `take_profit`, `risk/reward`, причины сигнала, veto, свежесть данных и предупреждения.

Проект остается advisory-only. Логика отправки private Bybit orders, управления позициями, grid lifecycle и автоматического исполнения не добавлялась.

## Карта проекта

- `app/api.py` — FastAPI endpoints и lightweight route registry для проверок импортируемости.
- `app/bybit_client.py` — Bybit V5 public REST market-data client, retry/backoff, rate-limit aware паузы.
- `app/strategies.py` — генерация стратегических сигналов и валидация `entry/SL/TP`.
- `app/recommendation.py` — каноническая классификация операторского решения `NO_TRADE` / `WAIT` / `REVIEW_ENTRY`.
- `app/operator_queue.py` — стабилизация очереди рекомендаций: один рынок — один операторский verdict.
- `app/mtf.py` — MTF consensus/veto для 15m/60m/240m.
- `app/safety.py` — freshness, stale-bar filtering, risk/reward diagnostics.
- `app/research.py` — rank кандидатов с backtest/ML/liquidity/LLM evidence.
- `app/backtest.py` — локальный баровый backtest стратегий.
- `app/ml.py`, `app/ml_background.py` — ML evidence и фоновые циклы обучения.
- `app/llm*.py` — фоновая LLM-оценка через Ollama-compatible endpoint.
- `app/signal_background.py` — автоконтур universe → market/sentiment → signals → evidence.
- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` — dark-mode operator cockpit.
- `tests/` — regression/unit/static/integration проверки.
- `README.md`, `docs/` — эксплуатационная документация и отчеты.

## Состояние до исправлений

1. Базовый прогон тестов падал на несогласованном дефолте `ML_AUTO_TRAIN_MAX_MODELS_PER_CYCLE`: тест ожидал безопасный лимит `2`, конфигурация фактически задавала `1`.
2. Система могла быть практически «немой» на широком universe: если liquidity snapshot отсутствовал, `_market_quality` превращал это в hard-block на этапе генерации стратегий. Оператор не видел даже `WAIT` или кандидата с entry/SL/TP и предупреждением.
3. Набор стратегий был слишком ориентирован на редкие экстремумы: Donchian breakout, squeeze, funding contrarian, OI confirmation, sentiment reversal. Для обычного трендового рынка за 1–2 дня могло не возникнуть ни одного полноценного кандидата.
4. Во frontend/help/docs оставались формулировки про «бота» и «создание бота», хотя система не содержит private-order execution. Это опасно смешивало advisory futures-рекомендации с несуществующей автоматической торговлей.
5. README неполно фиксировал новое поведение при отсутствии liquidity snapshot и не описывал практичный futures continuation setup.

## Исправления

### Trading/core

- Добавлен `trend_continuation_setup` — более частый, но защитный фьючерсный сетап продолжения тренда.
- Новый сетап формирует полноценные уровни `entry`, `stop_loss`, `take_profit` и расчетный `confidence`, но не обходит MTF/veto/risk/reward/research evidence.
- Отсутствующий liquidity snapshot больше не глушит генератор сигналов. Кандидат может быть создан с `liquidity_state="unknown"`, `is_eligible=None`, `spread_pct=None`; downstream-логика переводит это в предупреждения `liquidity_unknown` и `spread_unknown`.
- Известная плохая ликвидность (`is_eligible=false` при реальном snapshot) по-прежнему блокирует вход.
- `trend_continuation_setup` добавлен в `regime_adaptive_combo`, прямой генератор `build_latest_signals` и `STRATEGY_MAP` backtest.

### Backend/config

- Синхронизирован безопасный дефолт `ML_AUTO_TRAIN_MAX_MODELS_PER_CYCLE=2` в `app/config.py` и `.env.example`.
- Комментарии к фоновым LLM/backtest циклам уточнены: фоновые задачи не торгуют и не отправляют ордера.
- Проверена статическая область private execution: модулей отправки Bybit orders в проекте не найдено.

### Frontend/UI/UX

- UI-текст приведен к futures advisory-контракту: ручная проверка входа, а не создание бота.
- Название/eyebrow интерфейса уточнены как `Bybit Futures Advisory`.
- В селектор стратегии добавлен `trend_continuation_setup`.
- Объяснение протокола обновлено: `entry`, `SL`, `TP` используются оператором только после ручной проверки стакана, актуальной цены и риска.
- Добавлены человекочитаемые причины `trend_continuation_long` и `trend_continuation_short`.

### Документация

- README переименован по смыслу в `Bybit Futures Advisory Research Lab`.
- README уточняет, что проект — советующая СППР, а не система автоматического исполнения.
- Добавлено описание поведения при неизвестной liquidity snapshot: candidate допускается только с предупреждением, известная плохая ликвидность блокируется.
- Добавлено описание нового practical futures setup.

## Критичность найденных проблем

### Critical

- Потенциальная «немая система» из-за hard-block при отсутствующем liquidity snapshot: исправлено.
- Двусмысленность UI/документации вокруг «бота» при отсутствии order execution: исправлено в актуальных операторских текстах.

### High

- Слишком редкая генерация полноценных `LONG/SHORT` кандидатов на обычном трендовом рынке: добавлен `trend_continuation_setup`.
- Несогласованность test/config для ML auto-train throttling: исправлено.

### Medium

- README не фиксировал фактические допущения новой advisory логики: исправлено.
- Backtest strategy map не знал новый practical setup: исправлено.
- Отсутствие regression-теста на unknown liquidity → candidate with warning: добавлено.

### Low

- Остались исторические audit-документы, где `grid-bot` упоминается как отсутствующий/не реализованный модуль. Это не UI-контракт и не эксплуатационная инструкция, но при публичной передаче проекта лучше архивировать старые отчеты отдельно.

## Добавленные тесты

`tests/test_advisory_futures_recommendations.py` покрывает:

1. Генерацию futures continuation candidate с полноценными `entry/SL/TP` при отсутствующем liquidity snapshot.
2. Блокировку кандидата при известной плохой ликвидности.
3. Классификацию `REVIEW_ENTRY` при сильном сетапе и неизвестной liquidity/spread только как предупреждении, а не hard-veto.

## Обновленные тесты

- `tests/test_frontend_decision_ui.py` — ожидание advisory-only текста без формулировки про создание бота.
- `tests/test_ml_autotrain_cooldown.py` снова согласован с `app/config.py`.

## Остаточные риски

1. Проверка реального Bybit ingestion требует сети, PostgreSQL и актуального API; в изолированной среде это не подтверждает live market freshness.
2. Проект не содержит private execution, поэтому account/order reconciliation отсутствует намеренно.
3. Backtest остается баровым и не моделирует order book, queue position, частичные исполнения, liquidation engine и funding settlement.
4. LLM/ML evidence не должны считаться приказом на сделку; они только дополнительное объяснение/подтверждение.
5. Для production эксплуатации нужны внешний мониторинг, алерты по фоновым циклам, PostgreSQL backup/restore и контроль Bybit rate limits.

## Принятые допущения

- Отсутствие liquidity snapshot — это degraded state, а не доказательство плохой ликвидности. Поэтому генератор может показать кандидата с предупреждением, но оператор обязан проверить стакан вручную.
- Известная плохая ликвидность остается hard-block.
- Более частый futures setup допустим только как candidate generator; право на ручную проверку определяют MTF, confidence, R/R, freshness, spread/liquidity и downstream evidence.
- UI должен говорить о ручном входе по фьючерсу, а не о ботах.


## Проверки после правок

Выполнено в текущей среде:

- `python -m pytest -q tests` — `101 passed`, 2 предупреждения pytest-cache о правах записи `.pytest_cache`; функциональных падений нет.
- `node --check frontend/app.js` — синтаксических ошибок JavaScript нет.
- Статический grep по `place_order`, `create_order`, `/v5/order`, `send.*order`, `execute.*order` — модулей автоматической отправки ордеров не найдено.
- Targeted regression-набор по новым изменениям — `20 passed`.

Ограничения проверки:

- `python run.py check` в контейнере не удалось надежно завершить: команда зависала на шаге `compileall`/создании `__pycache__` из-за особенностей прав и фоновой индексации файлов в среде. Вместо этого выполнены полный pytest-набор и `node --check`.
- Реальный запуск FastAPI с PostgreSQL и Bybit market sync не проверялся end-to-end, так как требует внешней БД, сети и актуальной конфигурации `.env`.
