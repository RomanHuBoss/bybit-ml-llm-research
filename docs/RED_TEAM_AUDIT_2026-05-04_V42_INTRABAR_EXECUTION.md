# Red-team audit V42: intrabar SL/TP execution and strategy-quality hardening

Дата: 2026-05-04

## Краткое резюме

Проект уже был переведен в advisory-only режим с серверным recommendation contract, operator queue, guardrails, frontend cockpit и storage integrity слоями V38–V41. Дополнительная red-team проверка выявила критичный класс искажения backtest/outcome статистики: OHLC-свеча может одновременно содержать уровни stop-loss и take-profit, но порядок касания внутри свечи неизвестен. Если такую свечу считать take-profit без отдельной маркировки, качество стратегии систематически завышается.

V42 вводит единую консервативную модель исполнения `conservative_ohlc_stop_loss_first`: при одновременном касании SL и TP внутри одной OHLC-свечи результат считается stop-loss, но обязательно маркируется как неоднозначный `stop_loss_same_bar_ambiguous`. Эта неоднозначность теперь проходит через backtest, outcome evaluation, strategy quality, API-контракт и frontend.

## Найденные проблемы по критичности

### Critical

- Same-bar SL/TP ambiguity ранее не была полноценно сквозной сущностью: даже при conservative SL-first логике оператор и quality gate не получали достаточно явного признака, что результат зависит от неизвестного внутрисвечного порядка.
- Strategy quality могла оценивать статистику без отдельного штрафа за высокую долю сделок, где исход определяется OHLC-неоднозначностью.

### High

- Outcome evaluation не возвращал единый нормализованный набор notes для same-bar SL/TP: `same_bar_stop_first`, `ambiguous_exit`, `both_sl_tp_touched`, `intrabar_execution_model`.
- API quality endpoints и similar-history summary не показывали оператору количество conservative same-bar стопов.
- Frontend не выделял такие сделки отдельным warning-блоком и мог визуально смешивать обычный SL с неоднозначным SL-first.

### Medium

- Backtest не сохранял агрегаты `ambiguous_exit_count`, `ambiguous_exit_rate`, `exit_reason_counts` в явном виде.
- В `run_backtest` обнаружено дублирование записи точки equity curve внутри одной итерации, что могло искажать форму кривой капитала.
- PostgreSQL-схема не имела отдельного индекса/представления для диагностики доли same-bar ambiguous outcomes.

### Low

- README не фиксировал явное допущение по OHLC-внутрисвечному исполнению.
- UI-таблица истории похожих сигналов не имела отдельной колонки для SL/TP ambiguity.

## Внесенные исправления

### Trading logic / backtest

- В `app/backtest.py` добавлена функция `_intrabar_exit_reason()`.
- Для LONG: если `low <= stop_loss` и `high >= take_profit`, выход считается `stop_loss_same_bar_ambiguous` по цене stop-loss.
- Для SHORT: если `high >= stop_loss` и `low <= take_profit`, выход считается `stop_loss_same_bar_ambiguous` по цене stop-loss.
- В результат `run_backtest()` добавлены `intrabar_execution_model`, `same_bar_ambiguity`, `ambiguous_exit_count`, `ambiguous_exit_rate`, `exit_reason_counts`.
- Убрано дублирование точки equity curve.

### Outcome evaluation

- В `app/recommendation_outcomes.py` добавлены нормализованные notes для same-bar SL/TP.
- Outcome остается `hit_stop_loss`, но вместе с явной причиной `stop_loss_same_bar_ambiguous` и флагами ambiguity.

### Strategy quality

- В `app/strategy_quality.py` добавлены агрегаты ambiguity.
- Высокая доля `stop_loss_same_bar_ambiguous` снижает оценку качества.
- Стратегия не получает `APPROVED`, если статистика materially зависит от внутрисвечной неоднозначности.
- Для таких стратегий возвращается evidence grade `INTRABAR_UNCERTAINTY` и понятное русскоязычное объяснение.

### API contract

- В `app/trade_contract.py` добавлены поля `intrabar_execution_model`, `same_bar_stop_first_reason`, `is_ambiguous_intrabar_exit`.
- В `signal_breakdown.execution_model` сервер явно сообщает frontend, что same-bar SL/TP разрешается как SL-first.
- В `app/api.py` quality endpoints и similar-history summary возвращают `ambiguous_stop_first_count`.

### Frontend/UI

- В `frontend/app.js` добавлена визуальная маркировка ambiguous SL-first outcome.
- Similar-history summary показывает `same-bar SL-first`.
- Таблица похожих сигналов получила отдельную колонку `SL/TP`.
- В карточке рекомендации добавлен `OHLC model` с политикой `same-bar SL/TP ⇒ SL`.
- В `frontend/styles.css` добавлены стили warning-блока для внутрисвечной неоднозначности.

### PostgreSQL

- Добавлена миграция `sql/migrations/20260504_v42_intrabar_stop_first_quality.sql`.
- Добавлены индексы/ограничения для reason/notes diagnostics.
- Добавлены представления `v_intrabar_execution_quality_v42` и `v_backtest_intrabar_execution_quality_v42`.
- `sql/schema.sql` синхронизирован с V42.

### Documentation

- README дополнен разделом о модели исполнения SL/TP в OHLC backtest.
- Зафиксировано допущение: при неизвестном порядке цены внутри свечи используется conservative SL-first.

## Принятые допущения

- Без данных меньшего таймфрейма, tick/trade tape или достоверного моделирования внутрисвечного пути нельзя утверждать, что TP был достигнут раньше SL.
- Для советующей системы безопаснее занизить backtest-качество через SL-first, чем завысить его через optimistic TP-first.
- Same-bar ambiguity не означает, что стратегия автоматически плохая; она означает, что для high-confidence применения нужна проверка на более детальных данных.
- Публичный API-контракт сохранен как `recommendation_v40`, чтобы не ломать frontend/внешних потребителей. V42 добавляет совместимые поля, не требующие изменения старых клиентов.

## Добавленные тесты

Файл: `tests/test_recommendation_contract_v42.py`.

Покрытие:

- LONG same-bar SL/TP => `stop_loss_same_bar_ambiguous`.
- SHORT same-bar SL/TP => `stop_loss_same_bar_ambiguous`.
- Outcome evaluation возвращает `hit_stop_loss` с явными ambiguity notes.
- Strategy quality не допускает `APPROVED` при высокой доле ambiguous exits.
- Enriched recommendation contract, API metadata, frontend и SQL migration содержат intrabar execution policy.

## Проверки

Выполнено:

```bash
pytest -q
python run.py check
node --check frontend/app.js
python -m compileall -q app run.py install.py sitecustomize.py
```

Результат основного тестового набора: `219 passed`.

## Невыполненные проверки и остаточные риски

- В этой среде не выполнялось подключение к реальному PostgreSQL-инстансу пользователя.
- В этой среде не выполнялся live-запрос к Bybit.
- Не выполнялся полноценный browser/E2E прогон с DevTools console; frontend проверен статически через `node --check` и regression-тесты контракта.
- OHLC-backtest по-прежнему не восстанавливает реальный внутрисвечный путь цены; V42 делает этот риск явным, консервативным и измеримым.
