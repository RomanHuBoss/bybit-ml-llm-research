# Strategy quality gate — 2026-04-30

## Проблема

До этой ревизии система могла показывать оператору `REVIEW_ENTRY`, хотя evidence по стратегии был отсутствующим, слабым или статистически малым. В UI это выглядело как торговая рекомендация с противоречивой припиской: `Evidence notes: Бэктест слабый или малый`.

Это создавало неверный продуктовый контракт: оператор видел «рекомендацию», но фактически получал сырой исследовательский сетап.

## Новый контракт

Слабая или непроверенная стратегия больше не может попасть в торговую карточку ручного входа.

Операторские состояния теперь разделены так:

- `NO_TRADE` — есть hard-veto, вход запрещен.
- `WAIT` — рынок можно наблюдать, но текущий сетап не готов к проверке входа.
- `RESEARCH_CANDIDATE` — технический сетап существует, но стратегия не прошла статистическую квалификацию.
- `REVIEW_ENTRY` — сетап можно передать на ручную проверку только если стратегия имеет статус `APPROVED` или gate явно отключен настройкой.

## Strategy quality

Добавлен слой `strategy_quality`, который квалифицирует связку:

```text
category + symbol + interval + strategy
```

Статусы:

- `APPROVED` — стратегия прошла минимальные пороги сделок, PF, drawdown и total return.
- `WATCHLIST` — статистика частично приемлема, но еще недостаточна для торговой карточки.
- `RESEARCH` — данных мало, бэктест отсутствует или доказательность слабая.
- `REJECTED` — стратегия имеет отрицательные признаки качества.
- `STALE` — качество устарело и требует обновления.

Каноническая рекомендация теперь возвращает дополнительные поля:

```text
quality_status
quality_score
evidence_grade
quality_reason
quality_diagnostics
```

## Backtest matrix вместо backtest только свежего сигнала

Фоновый бэктестер переведен в режим `strategy_matrix`:

```text
symbols × intervals × strategies
```

Это означает, что система больше не ждет случайного свежего сигнала, чтобы узнать качество стратегии. Она заранее обновляет evidence по матрице стратегий, а live-кандидат затем сверяется с уже известным `strategy_quality`.

## API

Добавлены endpoints:

```text
GET  /api/strategies/quality
POST /api/strategies/quality/refresh
```

`/api/status` теперь показывает режим auto-backtest и параметры strategy quality gate.

## Настройки

Новые параметры `.env`:

```env
REQUIRE_STRATEGY_APPROVAL_FOR_REVIEW=true
STRATEGY_APPROVAL_MIN_TRADES=40
STRATEGY_APPROVAL_MIN_PROFIT_FACTOR=1.20
STRATEGY_APPROVAL_MAX_DRAWDOWN=0.25
STRATEGY_APPROVAL_MIN_TOTAL_RETURN=0.0
BACKTEST_AUTO_MAX_CANDIDATES=50
BACKTEST_AUTO_LIMIT=30000
BACKTEST_AUTO_TTL_HOURS=12
```

## UI

Frontend теперь отделяет research-сетапы от торговых карточек:

- добавлен фильтр `RESEARCH`;
- карточки `RESEARCH_CANDIDATE` имеют отдельный бейдж;
- raw table показывает колонку `Quality`;
- checklist показывает `strategy_quality`;
- слабый evidence больше не маскируется под `REVIEW_ENTRY`.

## Проверки

Выполнен полный regression-прогон:

```bash
pytest -q
```

Результат:

```text
120 passed
```
