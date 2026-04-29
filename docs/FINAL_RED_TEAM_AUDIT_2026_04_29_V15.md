# Финальный red-team аудит V15 — Bybit Futures Advisory Research Lab

Дата ревизии: 2026-04-29  
Режим: советующая СППР, без автоматической отправки ордеров.

## 1. Карта проекта

- `app/api.py` — import-light API слой, deferred FastAPI router, endpoints статуса, синхронизации рынка/sentiment, построения сигналов, MTF/latest, ranking, backtest, ML/LLM.
- `app/bybit_client.py` — публичный Bybit V5 REST client, retry/backoff, фильтр незакрытых свечей, candles/funding/open-interest/liquidity ingestion.
- `app/strategies.py` — генерация стратегических сигналов, market-quality filter, валидация направленных уровней, ML probability evidence.
- `app/mtf.py` — 15m/60m/240m MTF consensus, veto и context-only режимы.
- `app/recommendation.py` — каноническая серверная классификация `NO_TRADE` / `WAIT` / `REVIEW_ENTRY`.
- `app/operator_queue.py` — консолидация очереди и блокировка близких LONG/SHORT конфликтов.
- `app/safety.py` — freshness, directional R/R, аннотация stale/invalid-level сигналов.
- `app/research.py` — joins сигналов с backtest/ML/liquidity/LLM evidence и ранжирование.
- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` — vanilla JS dark trading cockpit.
- `tests/` — unit/static/regression tests для advisory safety, MTF, frontend contract, API static contract, resilience.
- `sql/schema.sql` — PostgreSQL schema.
- `.env.example`, `app/config.py` — runtime/configuration defaults.

Источники данных: публичные Bybit V5 market endpoints, PostgreSQL, optional sentiment feeds, optional local Ollama-compatible LLM. Private order execution отсутствует.

## 2. Состояние до исправлений

Проект был существенно продвинут после предыдущих ревизий: уже имел advisory-only ограничения, фильтрацию незакрытых свечей, MTF-veto, operator queue, dark UI, retry/backoff и набор regression-тестов. Однако при повторной жесткой проверке обнаружены критичные и высокие дефекты в местах, где разные слои системы расходились между собой: liquidity evidence не всегда попадал в серверное решение, unknown liquidity могла допустить слишком сильную рекомендацию, а frontend мог красиво отрисовать R/R даже для направленно неверных уровней.

## 3. Состояние после исправлений

Проект усилен без смены публичных API-контрактов:

- серверная выдача `/api/signals/latest` теперь включает liquidity fields до классификации операторского решения;
- unknown liquidity больше не может стать `REVIEW_ENTRY` при `REQUIRE_LIQUIDITY_FOR_SIGNALS=true`;
- явный `is_eligible=false` блокирует сигнал и не маскируется как отсутствие snapshot;
- frontend показывает invalid-level состояние и не считает R/R для перепутанных SL/TP;
- `.env.example` синхронизирован с безопасными дефолтами ML-auto-train;
- добавлены regression-тесты V15.

## 4. Найденные проблемы по критичности

### Critical

1. `/api/signals/latest` не присоединял последний liquidity snapshot, хотя `classify_operator_action()` рассчитывал решение с учетом `is_eligible` и `spread_pct`. Следствие: сервер мог классифицировать сигнал без фактической проверки ликвидности.
2. Unknown liquidity могла не блокировать переход в `REVIEW_ENTRY`, если остальные evidence были сильными. Для торговой СППР это опасно: оператор видел бы вход без подтверждения стакана/спреда.
3. Явный `is_eligible=false` в `_market_quality()` при нулевой ликвидности и spread=999 мог трактоваться как `unknown snapshot`, а не как hard block.
4. Frontend-счетчик R/R использовал абсолютные расстояния и мог показать нормальный R/R для LONG с `SL > entry` или SHORT с `TP > entry`.

### High

5. UI risk meter не получал штраф за направленно неверные уровни, если backend по какой-то причине вернул такую строку.
6. Конфигурационный пример расходился с кодовыми дефолтами ML-auto-train, что ухудшало воспроизводимость cold-start.
7. Серверная latest-очередь и research/rank имели разные evidence-поля; frontend пытался склеивать их на клиенте, что повышало риск рассогласованного решения.
8. Unknown liquidity не была зафиксирована как отдельное безопасное допущение в README.

### Medium

9. При отсутствии свежего snapshot система показывала недостаточно явное объяснение, почему вход не должен переходить в REVIEW.
10. Frontend не имел отдельного визуального состояния `invalid-levels` в execution map.
11. Тесты покрывали направленную валидацию на backend, но не фиксировали frontend-контракт «не показывать R/R для неверного порядка уровней».
12. Static API tests не контролировали наличие liquidity join в `/signals/latest`.

### Low

13. README не содержал отдельного описания ревизии V15 и новых safety-допущений.
14. CSS не выделял invalid-level карточку отдельным risk-стилем.

## 5. Что исправлено

- `app/api.py`: добавлены CTE `latest_liq_time` / `latest_liq` и поля liquidity в MTF и non-MTF ветки `/signals/latest`.
- `app/recommendation.py`: добавлено понятие `liquidity_required` / `liquidity_confirmed`; `REVIEW_ENTRY` невозможен без подтвержденной ликвидности при включенном `REQUIRE_LIQUIDITY_FOR_SIGNALS`.
- `app/strategies.py`: `_market_quality()` теперь различает реально отсутствующий snapshot (`is_eligible is None`) и явный `is_eligible=false`.
- `frontend/app.js`: добавлены `levelsProblem()` и `levelsProblemText()`; `riskReward()` стал направленно безопасным; execution map и risk meter учитывают invalid-level сценарий.
- `frontend/styles.css`: добавлено визуальное состояние `.execution-map.invalid-levels` и `.execution-level.invalid`.
- `.env.example`: синхронизированы ML-auto-train дефолты с `app/config.py`.
- `tests/test_core_safety.py`: обновлено ожидание по explicit non-eligible liquidity.
- `tests/test_red_team_advisory_safety_v15.py`: добавлены regression-тесты на liquidity gating, API liquidity join и frontend directional R/R contract.
- `README.md`: добавлен раздел V15 с новыми safety-границами и командами проверки.

## 6. Торгово-логические ошибки

- Исправлено: unknown liquidity больше не является достаточным условием для входа.
- Исправлено: explicit non-eligible liquidity не может пройти как unknown.
- Исправлено: UI не показывает R/R для уровней, противоречащих направлению.
- Остаточный риск: стратегии по-прежнему rule-based и не гарантируют прибыльность; operator review обязателен.

## 7. Архитектурные ошибки

- Исправлено: `/signals/latest` и `/research/rank` стали ближе по набору evidence-полей, что уменьшает риск frontend/backend рассинхронизации.
- Остаточный риск: проект не содержит durable state machine для реального исполнения, что допустимо только потому, что он advisory-only.

## 8. Backend/Core ошибки

- Исправлено: hard/soft gating по liquidity перенесен в единый server-side decision path.
- Исправлено: дефолты env/code синхронизированы для ML-auto-train.
- Остаточный риск: без PostgreSQL и свежей загрузки рынка часть runtime-проверок не может быть выполнена в sandbox.

## 9. Frontend/UI/UX ошибки

- Исправлено: invalid-level состояние стало видимым в execution map.
- Исправлено: risk meter получает дополнительный штраф за invalid-level сценарий.
- Исправлено: R/R отображается как `—`, если уровни не соответствуют LONG/SHORT.
- Остаточный риск: график остается custom/placeholder, а не полноценным TradingView/lightweight-charts виджетом.

## 10. JavaScript-ошибки

- Исправлено: `riskReward()` больше не является направленно слепым.
- Проверено: `node --check frontend/app.js` завершился с кодом 0.

## 11. Надежность и отказоустойчивость

- Улучшено: при отсутствии liquidity snapshot система деградирует в `WAIT`, а не в `REVIEW_ENTRY`.
- Улучшено: frontend не падает и показывает explicit invalid-level reason.
- Остаточный риск: live Bybit/API и PostgreSQL интеграция не проверялись в этой среде из-за отсутствия реального окружения.

## 12. Тестовое покрытие

Добавлены тесты:

- `test_unknown_liquidity_cannot_be_review_entry_when_liquidity_required`;
- `test_confirmed_liquidity_can_still_reach_review_entry`;
- `test_latest_signals_api_contract_includes_liquidity_join_for_operator_decision`;
- `test_frontend_directional_risk_reward_does_not_show_absolute_rr_for_bad_levels`.

Обновлены тесты:

- `test_strategy_allows_missing_liquidity_snapshot_only_as_warning_candidate`;
- `test_strategy_blocks_explicit_noneligible_liquidity_snapshot`.

Проверки, выполненные в sandbox:

- `node --check frontend/app.js` — пройдено;
- `python -S -m py_compile app/*.py run.py install.py sitecustomize.py` — пройдено;
- прямой Python-check `classify_operator_action()` для confirmed/unknown liquidity — пройдено;
- `tests/test_red_team_advisory_safety_v15.py` один раз прошел: `4 passed in 0.03s`.

Ограничение проверки: полный `pytest` в данной sandbox-среде нестабилен из-за зависания Python-процессов при scientific stack/pytest завершении. Это наблюдалось как инфраструктурная проблема среды, а не как падение assertions. Для локальной проверки используйте чистый venv и команды README.

## 13. Расхождения код ↔ документация ↔ конфигурация

- Исправлено: `.env.example` приведен к безопасным дефолтам из `app/config.py`.
- Исправлено: README описывает новое liquidity-допущение и V15-команды проверки.

## 14. Безопасность

- Автоматическая торговля не добавлялась.
- Private Bybit credentials не требуются.
- Live order execution, signed private requests, account reconciliation, order outbox и kill-switch отсутствуют намеренно, потому что система советующая.
- Остаточный риск: если в будущем появится private execution, потребуется отдельный audited execution module; текущий проект не должен использоваться как trading bot.

## 15. Список измененных файлов

- `.env.example` — синхронизация ML-auto-train defaults.
- `README.md` — добавлен раздел V15.
- `app/api.py` — liquidity join в `/signals/latest`.
- `app/recommendation.py` — gating `REVIEW_ENTRY` по подтвержденной ликвидности.
- `app/strategies.py` — явный non-eligible больше не маскируется как unknown.
- `frontend/app.js` — directional-level validation в UI R/R.
- `frontend/styles.css` — invalid-level visual state.
- `tests/test_core_safety.py` — обновлены liquidity edge-case тесты.
- `tests/test_red_team_advisory_safety_v15.py` — новый regression-файл.
- `docs/FINAL_RED_TEAM_AUDIT_2026_04_29_V15.md` — данный отчет.

Удаленных файлов нет.
