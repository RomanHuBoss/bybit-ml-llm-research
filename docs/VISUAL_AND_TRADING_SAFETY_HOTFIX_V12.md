# Visual and trading-safety hotfix v12 — 2026-04-28

Основание: повторная проверка архива `bybit-ml-llm-research-main(6).zip` и пользовательские скриншоты с артефактами badge в `Candidate Queue`, `MTF матрица` и верхней панели.

## Исправления UI/UX

- Длинный операторский статус `РУЧНАЯ ПРОВЕРКА ВХОДА` больше не выводится в узком badge очереди целиком. В очереди используется компактная форма `ПРОВЕРКА`, полный текст сохранен в `title` и `aria-label`.
- MTF action badge получил компактные формы `MTF OK`, `BIAS OK`, `ENTRY X`, `NO MTF`, чтобы не раздвигать правую аналитическую панель.
- CSS дополнен v12-слоем: фиксированная геометрия очереди, устойчивые колонки status/score, защита от переполнения, корректные ellipsis и мобильные overrides.
- Версии static assets подняты до `trading-cockpit-v12`, чтобы браузер не держал старые CSS/JS.

## Исправления trading-safety

- `app.recommendation` проверяет порядок уровней относительно направления. Абсолютный R/R больше не может пропустить LONG с `stop_loss > entry` или SHORT с `take_profit > entry`.
- `app.mtf` вводит `entry_tf_conflict`: если агрегированная картина entry-TF сильнее против конкретного кандидата, кандидат получает hard MTF veto.
- `app.mtf` группирует MTF-контекст по `(category, symbol)`, чтобы не смешивать `linear`, `spot`, `inverse`.
- `/api/signals/latest` теперь принимает `category` и фильтрует сигналы по выбранному рынку.
- Frontend fallback `/api/signals/latest` вызывает API с текущей категорией.

## Проверки

```bash
node --check frontend/app.js
python -S -m compileall -q app tests install.py run.py sitecustomize.py
```

Прямой import-light runner: 28 тестов прошли. Полный `pytest` в контейнере не завершился из-за зависания runner/import окружения; внешние PostgreSQL/Bybit/Ollama не поднимались.

## Оставшиеся ограничения

- Система остается советующей СППР и не должна исполнять ордера.
- EXIT без реального position-state остается неполным доменным сценарием.
- Для production execution нужен отдельный execution-layer с account sync, kill-switch, durable outbox и idempotency.
