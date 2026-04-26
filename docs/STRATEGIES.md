# Стратегии проекта

В проекте реализованы исследовательские шаблоны. Это не готовые гарантированно прибыльные стратегии. Перед paper/live они должны пройти out-of-sample и walk-forward проверку.

## 1. Donchian/ATR trend breakout

Пробой 20-барного high/low в сторону EMA-тренда.

Long:

```text
close > DonchianHigh(20)
EMA20 > EMA50
volume_z желательно > 0
micro_sentiment_score не против движения
```

Риск:

```text
SL = entry - 1.8 * ATR
TP = entry + 3.0 * ATR
```

## 2. EMA pullback trend-following

Покупка отката в uptrend или short-отката в downtrend.

Long:

```text
EMA20 > EMA50 > EMA200
RSI 38–55
close >= EMA50
```

## 3. Bollinger/RSI mean reversion

Возврат к среднему в слабом тренде.

Long:

```text
bb_position < 0.08
RSI < 32
abs(EMA20/EMA50 - 1) < 2.5%
```

## 4. Volatility squeeze breakout

Низкая ширина Bollinger Bands + всплеск объёма.

```text
BB width <= 20-й перцентиль за 120 баров
volume_z > 0.5
```

## 5. Funding extreme contrarian

Переполненность long/short через funding.

Short:

```text
funding_rate > 0.08%
RSI > 64
```

Long:

```text
funding_rate < -0.08%
RSI < 36
```

## 6. Open Interest trend confirmation

Тренд подтверждается, когда цена и OI расширяются вместе.

```text
long:  oi_change_24 > 2.5%, ret_12 > 1.5%, EMA20 > EMA50
short: oi_change_24 > 2.5%, ret_12 < -1.5%, EMA20 < EMA50
```

## 7. Sentiment reversal

Экстремальный Fear/Greed используется только вместе с техническим истощением.

```text
extreme fear + RSI < 35 -> possible long reversal
extreme greed + RSI > 70 -> possible short reversal
```

## 8. Regime adaptive combo

Метастратегия, которая собирает голоса нескольких стратегий и открывает сигнал только при согласовании.

```text
long_score  = sum(confidence of long candidates)
short_score = sum(confidence of short candidates)
entry       = лучшая стратегия в доминирующем направлении
```

Цель — не заменить отдельные стратегии, а выделить моменты, когда несколько независимых сетапов указывают в одну сторону.

## 9. ML ranking

ML не генерирует “истину”. Он ранжирует состояние рынка и найденные сетапы.

Признаки:

```text
returns: 1/3/12/24 бара
EMA gaps
RSI
ATR%
Bollinger position/width
realized volatility
volume_z
funding_rate
open interest change
sentiment_score
news_sentiment_score
micro_sentiment_score
liquidity_score
spread_pct
```

## 10. Research ranking endpoint

`GET /api/research/rank` объединяет:

```text
signal confidence
последний backtest по symbol+strategy
profit_factor
sharpe
win_rate
max_drawdown penalty
последний ROC AUC ML-модели
liquidity_score
spread_pct
```

Это основной экран для выбора кандидатов на paper-trading.

## Минимальные требования перед использованием

- 500–1000+ баров истории;
- отдельный out-of-sample период;
- учтены комиссии и slippage;
- минимум 50–100 сделок на стратегию;
- сравнение против buy-and-hold/random baseline;
- проверка по разным режимам рынка;
- live trading запрещён до отдельного аудита.

## Audit hardening v2.1

### Исполнение в бэктесте

Сигнал формируется на полностью закрытой свече, но вход моделируется только по `open` следующей свечи. Это снижает риск lookahead bias. Stop-loss и take-profit пересчитываются относительно фактически исполняемой цены входа с сохранением дистанций, рассчитанных стратегией.

Если в одной свече после входа одновременно достижимы SL и TP, движок выбирает SL. Это консервативное допущение, потому что внутрисвечная последовательность high/low неизвестна.

### Liquidity gate

Стратегии не должны генерировать рекомендации без подтверждённой ликвидности. По умолчанию `REQUIRE_LIQUIDITY_FOR_SIGNALS=true`, поэтому инструмент должен иметь свежий liquidity snapshot, пройти `is_eligible=true` и иметь spread не хуже `MAX_SPREAD_PCT`.

### Universe gate

Core symbols больше не являются безусловно допустимыми. Если инструмент из `CORE_SYMBOLS` не прошёл liquidity-фильтр, он не попадёт в universe, если явно не включить `ALLOW_UNVERIFIED_CORE_SYMBOLS=true`. Это сделано для защиты от устаревших или уже неликвидных инструментов.

### ML target

Последние `horizon_bars` строк исключаются из обучения, потому что будущая доходность для них неизвестна. Их нельзя считать отрицательным классом.
