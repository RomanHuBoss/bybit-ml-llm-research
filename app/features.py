from __future__ import annotations

import pandas as pd

from .db import query_df
from .indicators import add_indicators


FEATURE_COLUMNS = [
    "ret_1",
    "ret_3",
    "ret_12",
    "ret_24",
    "ema20_gap",
    "ema50_gap",
    "ema200_gap",
    "ema20_50_gap",
    "rsi_14",
    "atr_pct",
    "bb_position",
    "bb_width",
    "rv_24",
    "volume_z",
    "funding_rate",
    "oi_change_24",
    "sentiment_score",
    "news_sentiment_score",
    "micro_sentiment_score",
    "liquidity_score",
    "spread_pct",
]


def load_market_frame(category: str, symbol: str, interval: str, limit: int = 5000) -> pd.DataFrame:
    df = query_df(
        """
        SELECT start_time, open, high, low, close, volume, turnover
        FROM candles
        WHERE category=%s AND symbol=%s AND interval=%s
        ORDER BY start_time DESC
        LIMIT %s
        """,
        (category, symbol.upper(), interval, limit),
    )
    if df.empty:
        return df
    df = df.sort_values("start_time").reset_index(drop=True)
    df = add_indicators(df)

    funding = query_df(
        """
        SELECT funding_time, funding_rate
        FROM funding_rates
        WHERE category=%s AND symbol=%s
        ORDER BY funding_time
        """,
        (category, symbol.upper()),
    )
    if not funding.empty:
        funding["funding_rate"] = pd.to_numeric(funding["funding_rate"], errors="coerce")
        df = pd.merge_asof(
            df.sort_values("start_time"),
            funding.rename(columns={"funding_time": "start_time"}).sort_values("start_time"),
            on="start_time",
            direction="backward",
        )
    else:
        df["funding_rate"] = 0.0

    oi = query_df(
        """
        SELECT ts, open_interest
        FROM open_interest
        WHERE category=%s AND symbol=%s
        ORDER BY ts
        """,
        (category, symbol.upper()),
    )
    if not oi.empty:
        oi["open_interest"] = pd.to_numeric(oi["open_interest"], errors="coerce")
        df = pd.merge_asof(
            df.sort_values("start_time"),
            oi.rename(columns={"ts": "start_time"}).sort_values("start_time"),
            on="start_time",
            direction="backward",
        )
        df["oi_change_24"] = df["open_interest"].pct_change(24)
    else:
        df["open_interest"] = 0.0
        df["oi_change_24"] = 0.0

    daily = query_df(
        """
        SELECT day,
               AVG(score)::float AS sentiment_score,
               (AVG(score) FILTER (WHERE source IN ('gdelt_news','rss_news','cryptopanic_news')))::float AS news_sentiment_score
        FROM sentiment_daily
        WHERE symbol IN (%s, 'MARKET')
        GROUP BY day
        ORDER BY day
        """,
        (symbol.upper(),),
    )
    if not daily.empty:
        df["day"] = pd.to_datetime(df["start_time"]).dt.date
        daily["day"] = pd.to_datetime(daily["day"]).dt.date
        df = df.merge(daily, on="day", how="left")
        df["sentiment_score"] = df["sentiment_score"].ffill().fillna(0.0)
        df["news_sentiment_score"] = df["news_sentiment_score"].ffill().fillna(0.0)
    else:
        df["sentiment_score"] = 0.0
        df["news_sentiment_score"] = 0.0

    intraday = query_df(
        """
        SELECT ts, AVG(score)::float AS micro_sentiment_score
        FROM sentiment_intraday
        WHERE symbol=%s AND interval=%s
        GROUP BY ts
        ORDER BY ts
        """,
        (symbol.upper(), interval),
    )
    if not intraday.empty:
        intraday["micro_sentiment_score"] = pd.to_numeric(intraday["micro_sentiment_score"], errors="coerce")
        df = pd.merge_asof(
            df.sort_values("start_time"),
            intraday.rename(columns={"ts": "start_time"}).sort_values("start_time"),
            on="start_time",
            direction="backward",
        )
        df["micro_sentiment_score"] = df["micro_sentiment_score"].ffill().fillna(0.0)
    else:
        df["micro_sentiment_score"] = 0.0

    liquidity = query_df(
        """
        SELECT captured_at AS start_time, liquidity_score, spread_pct
        FROM liquidity_snapshots
        WHERE category=%s AND symbol=%s
        ORDER BY captured_at
        """,
        (category, symbol.upper()),
    )
    if not liquidity.empty:
        liquidity["liquidity_score"] = pd.to_numeric(liquidity["liquidity_score"], errors="coerce")
        liquidity["spread_pct"] = pd.to_numeric(liquidity["spread_pct"], errors="coerce")
        df = pd.merge_asof(
            df.sort_values("start_time"),
            liquidity.sort_values("start_time"),
            on="start_time",
            direction="backward",
        )
    else:
        df["liquidity_score"] = 0.0
        df["spread_pct"] = 0.0

    df["ema20_gap"] = df["close"] / df["ema_20"] - 1
    df["ema50_gap"] = df["close"] / df["ema_50"] - 1
    df["ema200_gap"] = df["close"] / df["ema_200"] - 1
    df["ema20_50_gap"] = df["ema_20"] / df["ema_50"] - 1
    df["bb_position"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)
    return df


def build_ml_dataset(category: str, symbol: str, interval: str, horizon_bars: int = 12) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    df = load_market_frame(category, symbol, interval)
    if df.empty:
        return pd.DataFrame(), pd.Series(dtype=int), df
    df["future_ret"] = df["close"].shift(-horizon_bars) / df["close"] - 1
    threshold = df["atr_pct"].rolling(100).median().fillna(df["atr_pct"].median()) * 0.35
    df["target"] = (df["future_ret"] > threshold).astype(int)
    clean = df.dropna(subset=FEATURE_COLUMNS + ["target"]).copy()
    X = clean[FEATURE_COLUMNS].replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)
    y = clean["target"].astype(int)
    return X, y, clean
