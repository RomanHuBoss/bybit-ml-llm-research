# V26 Red-team audit: provisional entry gate

## Симптом

Production UI после V25 продолжал показывать `Trading Desk = 0`, максимум `RESEARCH`, хотя Strategy Lab показывал approved-строки.

## Корневая причина

V25 восстановил передачу quality evidence в `/api/signals/latest`, но сам gate оставался слишком бинарным:

1. `Approved` KPI считал все TF, включая 60m/240m контекст, тогда как операторская очередь принимает только 15m entry-кандидаты.
2. Для каждого `symbol+15m+strategy` требовалось минимум 40 сделок. При 5 днях live-работы и большом universe fresh-сетапы часто имели 10-39 локальных сделок и поэтому навсегда оставались `RESEARCH_CANDIDATE`, даже если остальные hard-фильтры были зелеными.

## Исправление

Добавлен advisory-only `PROVISIONAL_REVIEW` режим:

- статус API остается `operator_action=REVIEW_ENTRY`, чтобы сетап попал в фильтр «Вход»;
- `operator_quality_mode=provisional` отделяет его от полного `APPROVED`;
- label: `ПИЛОТНАЯ ПРОВЕРКА ВХОДА`;
- `operator_trust_status=PROVISIONAL_REVIEW` подсвечивается как warning, не как полный trust-pass;
- REJECTED, STALE, отрицательный PF, hard MTF/liquidity/spread/RR/freshness/confidence veto по-прежнему блокируют entry.

## Безопасное допущение

Для советующей СППР ручная проверка сетапа с малой, но не отрицательной выборкой лучше, чем вечная Research-очередь. Это не меняет advisory-only контракт: система не отправляет ордера и не должна исполнять сделку без оператора.

## Проверки

Добавлены regression-тесты на:

- provisional REVIEW_ENTRY при малой, но положительной выборке;
- запрет provisional при слабом PF;
- отображение PROVISIONAL в frontend;
- KPI `Approved 15m/all`.
