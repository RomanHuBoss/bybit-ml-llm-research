# Red-team audit V32 — similar history and operator contract

## Найденные проблемы

1. В UI была кнопочная логика действий оператора, но экран подробностей не давал отдельной истории похожих завершённых рекомендаций по тому же `symbol + interval + strategy + direction`.
2. API качества агрегировал результаты по сегментам, но не было точечного endpoint, который объясняет текущую карточку через похожие исторические исходы.
3. `recommendation_operator_actions.recommendation_status` хранился как свободный текст без DB-side ограничения допустимых статусов UI-контракта.
4. Для выборки похожих исходов не было специализированного индекса; при росте таблицы `signals` история могла стать тяжелой.

## Что изменено

- Добавлен `GET /api/recommendations/{signal_id}/similar-history`.
- Добавлен helper `_similar_recommendation_history`, который возвращает summary и последние исходы похожих рекомендаций.
- Frontend теперь показывает блок `История похожих сигналов` в карточке подробностей.
- Добавлены loading/error/empty states для истории похожих сигналов.
- Добавлена миграция `20260503_v32_similar_history_and_operator_contract.sql`.
- Добавлены индексы `idx_signals_similarity_lookup_v32` и `idx_recommendation_outcomes_terminal_v32`.
- Добавлен CHECK `ck_recommendation_operator_actions_status_v32`.
- Добавлен view `v_recommendation_similar_history` для диагностики и ручной SQL-проверки.

## Контракт

История похожих сигналов не является вероятностью прибыли. Она используется как evidence-слой: размер выборки, realized R, MFE/MAE, PF и winrate помогают понять, насколько статистика похожих рекомендаций вообще заслуживает доверия.
