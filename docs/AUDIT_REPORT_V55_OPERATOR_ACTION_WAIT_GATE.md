# V55 audit report: paper_opened не должен быть доступен для WAIT

## Дефект

После V54 `primary_next_action` и кнопки действий оператора могли расходиться с текущим server-owned статусом рекомендации. При клике `paper_opened` сервер корректно отвечал:

```text
paper_opened_allowed_only_for_review_entry: current_status=wait
```

Это означает, что backend-защита сработала, но UI допустил опасную попытку действия, которое не соответствует текущему контракту.

## Риск

Для советующей торговой системы это high-риск UX/согласованности: оператор видит действие входа там, где серверный контракт уже находится в защитном состоянии `WAIT/NO_TRADE`. Даже если backend отклоняет действие, интерфейс не должен провоцировать неверное решение.

## Исправление

- Удалён безусловный набор кнопок operator actions в trade ticket.
- Добавлен `operatorActionButtonsHtml(contract)`.
- UI теперь строит кнопки из `recommendation.next_actions` и `primary_next_action`.
- `paper_opened` проходит frontend gate только при полном server-owned условии:
  - `recommendation_status=review_entry`;
  - `trade_direction=long|short`;
  - `is_actionable=true`;
  - `contract_health.ok=true`;
  - `price_actionability.is_price_actionable=true`;
  - `price_status=entry_zone`.
- Disabled-кнопки игнорируются click-handler'ом.
- После server-gate rejection UI обновляет rank/signals, чтобы оператор видел актуальное состояние.

## Проверки

Добавлены regression-тесты:

- `test_v55_wait_contract_does_not_offer_paper_opened_next_action`;
- `test_v55_frontend_renders_operator_buttons_from_server_next_actions_only`;
- `test_v55_frontend_no_longer_renders_unconditional_paper_button`.

## Итог

`paper_opened` остаётся разрешённым только как advisory paper-отметка для `REVIEW_ENTRY` после ручного подтверждения. Для `WAIT/NO_TRADE` UI больше не предлагает вход, а backend gate остаётся последней линией защиты для старых клиентов/API-вызовов.
