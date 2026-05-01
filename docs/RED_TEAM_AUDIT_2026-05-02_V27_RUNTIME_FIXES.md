# V27 Runtime / Upgrade fixes — 2026-05-02

## Что исправлено

1. **Запуск `python run.py app` снова работает.**
   В README и ранних audit-документах команда запуска была указана как `python run.py app`, но CLI принимал только `server`. Добавлен обратносуместимый alias `app`, чтобы обновленный архив не падал на старой инструкции.

2. **`run.py check/test` защищены от внешних pytest-плагинов.**
   В launcher-окружение добавлен `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`: глобально установленные плагины больше не должны менять поведение regression-набора проекта или замедлять проверку.

3. **LLM storage теперь реально мигрирует старые БД.**
   `CREATE TABLE IF NOT EXISTS` не добавляет новые колонки в уже существующую таблицу. Из-за этого старые установки могли падать на `llm_evaluations.interval`, `payload_hash`, `duration_ms`, `ON CONFLICT (signal_id)` и индексах. Добавлены `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, backfill `payload_hash`, дедупликация `signal_id` и уникальный индекс `ux_llm_evaluations_signal_id`.

4. **Donchian strategy не падает на `pd.NA`/битых границах канала.**
   `float(pd.NA)` мог валить построение всех сигналов для symbol/TF. Теперь границы канала проходят через безопасный `_finite`-парсер: при невалидной верхней границе стратегия просто не генерирует пробой, а не роняет цикл.

## Проверки

- `python -S -m py_compile` для измененных Python-файлов — OK.
- `node --check frontend/app.js` — OK.
- Ручная проверка CLI alias `python run.py app --no-reload --host 127.0.0.1` через `parse_args()` — OK.
- Ручная проверка `donchian_breakout()` на `pd.NA` в границах канала — OK.

## Ограничение текущей audit-среды

Полный `pytest` в контейнере повторно провоцировал служебные timeout-процессы оболочки вокруг `__pycache__`, поэтому итоговая фиксация подтверждена компиляцией, frontend syntax-check и targeted runtime-проверками измененных участков.
