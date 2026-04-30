# V20 — Strategy Lab, Trading Desk diagnostics и walk-forward evidence

## Что исправлено

Проект больше не показывает слабую исследовательскую строку как торговую рекомендацию. V20 добавляет отдельный аналитический слой Strategy Lab и диагностику Trading Desk:

- `APPROVED` стратегии допускаются в Trading Desk.
- `WATCHLIST` остаётся в наблюдении.
- `RESEARCH` остаётся исследовательским кандидатом.
- `REJECTED` блокируется как торговый сетап.

## Новые backend-компоненты

### `app/strategy_lab.py`

Собирает Strategy Lab payload:

- воронка статусов;
- причины недопуска;
- список approved-стратегий;
- near-approval кандидаты;
- rejected-срез;
- диагностика пустого Trading Desk.

### Новые API

```text
GET /api/strategies/lab
GET /api/trading-desk/diagnostics
```

### Расширенный `strategy_quality`

Добавлены поля:

```text
expectancy
avg_trade_pnl
median_trade_pnl
last_30d_return
last_90d_return
walk_forward_pass_rate
walk_forward_windows
walk_forward_summary
```

## Walk-forward / stability proxy

После сохранения `backtest_trades` quality-слой делит сделки на rolling windows и считает долю окон, где стратегия не разваливается. Это не заменяет полноценный parameter walk-forward optimization, но уже отсекает стратегии, у которых общий PF создаётся одним удачным отрезком.

## Frontend

Добавлен блок `Strategy Lab`:

- summary: Approved / Watch / Research / Rejected;
- Trading Desk diagnostics;
- таблица стратегий с PF, DD, Trades, WF и blocker;
- кнопка `Quality refresh`.

Если Trading Desk пуст, UI теперь объясняет причину: сколько сетапов было найдено, сколько прошло quality gate, какие blocker-коды чаще всего остановили вход.

## Контрольный quality snapshot

В `docs/QUALITY_SNAPSHOT_2026-04-30.json` сохранён пример выгрузки:

```text
total=56
approved=3
watchlist=3
research=32
rejected=18
```

По этому snapshot система должна показывать, что Trading Desk не сломан: есть 3 approved-стратегии, но остальные не имеют права выглядеть как торговые рекомендации.
