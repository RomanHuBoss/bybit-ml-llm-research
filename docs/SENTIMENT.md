# Сентимент: бесплатный pipeline без CryptoPanic

CryptoPanic оставлен как опциональный premium-plugin. Базовая система полностью работает без платных ключей.

## Источники в проекте

### 1. Alternative.me Fear & Greed Index

Дневной рыночный режим для BTC/крипторынка. Значение переводится в диапазон `[-1; +1]`:

```text
score = (value - 50) / 50
```

Использование:

- extreme fear + техническое истощение продавцов → осторожный mean-reversion long;
- extreme greed + перегретый RSI/funding → осторожный contrarian short;
- нейтральный режим → не усиливать сигнал.

### 2. GDELT DOC API

Бесплатный глобальный новостной поток. По каждому символу строится поисковый запрос, например:

```text
(bitcoin OR BTC) crypto market
(solana OR SOL) crypto market
```

Для заголовков сохраняются:

- `vader` sentiment score;
- опциональный `llm_score`, если включен `use_llm=true`;
- домен источника;
- дата публикации;
- raw JSON.

### 3. RSS крупных крипто-СМИ

По умолчанию подключены RSS-ленты:

```env
RSS_URLS=https://www.coindesk.com/arc/outboundfeeds/rss/|CoinDesk,https://cointelegraph.com/rss|Cointelegraph
```

RSS не требует ключей и даёт стабильный поток заголовков. Система раскладывает новости по `MARKET` и по конкретным тикерам, если заголовок содержит символ/алиас.

### 4. Market-derived sentiment

Это не внешний sentiment, а состояние самого рынка:

```text
micro_score = f(ret_24, ema20_50_gap, oi_change_24, funding_rate, volume_z)
```

Сохраняется в `sentiment_intraday` и попадает в ML-признаки как `micro_sentiment_score`.

Логика:

- рост цены + рост OI → подтверждение тренда;
- высокий positive funding → crowding longs, contrarian penalty;
- высокий negative funding → crowding shorts, contrarian boost для long;
- volume_z усиливает только уже существующее движение.

### 5. Локальная LLM

LLM не предсказывает цену и не принимает торговые решения. Она используется для:

- классификации заголовков: bullish / bearish / neutral;
- объяснения сигнала;
- выявления противоречий между техническим сетапом, funding, OI и новостями;
- формирования risk brief для дашборда.

## Таблицы

```text
sentiment_daily      # дневной Fear&Greed, GDELT/RSS/CryptoPanic агрегаты
sentiment_intraday   # market_microstructure по свечам
news_items           # заголовки и raw JSON
```

## Как использовать в ML

В `features.py` добавлены признаки:

```text
sentiment_score
news_sentiment_score
micro_sentiment_score
liquidity_score
spread_pct
```

Сентимент не должен использоваться как самостоятельный сигнал. Он выступает как фильтр/усилитель уже найденного сетапа.

## Как не использовать сентимент

Нельзя:

- покупать потому, что “все bullish”;
- торговать headline без проверки цены, ликвидности и funding;
- использовать социальный шум без истории ошибок;
- смешивать источники без весов доверия.

Правильнее:

- технический сигнал сначала;
- затем фильтр ликвидности;
- затем проверка funding/OI;
- затем news/LLM brief;
- затем backtest/walk-forward.
