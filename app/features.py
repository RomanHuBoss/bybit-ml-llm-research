from __future__ import annotations

import pandas as pd

from .db import query_df
from .indicators import add_indicators


from .feature_schema import FEATURE_COLUMNS


def _to_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


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
    df["start_time"] = _to_utc(df["start_time"])
    df = df.dropna(subset=["start_time"]).sort_values("start_time").reset_index(drop=True)
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
        funding["start_time"] = _to_utc(funding.pop("funding_time"))
        funding = funding.dropna(subset=["start_time"]).sort_values("start_time")
        df = pd.merge_asof(df.sort_values("start_time"), funding, on="start_time", direction="backward")
        df["funding_rate"] = df["funding_rate"].ffill().fillna(0.0)
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
        oi["start_time"] = _to_utc(oi.pop("ts"))
        oi = oi.dropna(subset=["start_time"]).sort_values("start_time")
        df = pd.merge_asof(df.sort_values("start_time"), oi, on="start_time", direction="backward")
        df["open_interest"] = df["open_interest"].ffill().fillna(0.0)
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
        df["day"] = pd.to_datetime(df["start_time"], utc=True).dt.date
        daily["day"] = pd.to_datetime(daily["day"], errors="coerce").dt.date
        daily = daily.dropna(subset=["day"])
        df = df.merge(daily, on="day", how="left")
        df["sentiment_score"] = pd.to_numeric(df["sentiment_score"], errors="coerce").ffill().fillna(0.0)
        df["news_sentiment_score"] = pd.to_numeric(df["news_sentiment_score"], errors="coerce").ffill().fillna(0.0)
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
        intraday["start_time"] = _to_utc(intraday.pop("ts"))
        intraday = intraday.dropna(subset=["start_time"]).sort_values("start_time")
        df = pd.merge_asof(df.sort_values("start_time"), intraday, on="start_time", direction="backward")
        df["micro_sentiment_score"] = df["micro_sentiment_score"].ffill().fillna(0.0)
    else:
        df["micro_sentiment_score"] = 0.0

    liquidity = query_df(
        """
        SELECT captured_at AS start_time, liquidity_score, spread_pct, is_eligible
        FROM liquidity_snapshots
        WHERE category=%s AND symbol=%s
        ORDER BY captured_at
        """,
        (category, symbol.upper()),
    )
    if not liquidity.empty:
        liquidity["start_time"] = _to_utc(liquidity["start_time"])
        liquidity["liquidity_score"] = pd.to_numeric(liquidity["liquidity_score"], errors="coerce")
        liquidity["spread_pct"] = pd.to_numeric(liquidity["spread_pct"], errors="coerce")
        liquidity = liquidity.dropna(subset=["start_time"]).sort_values("start_time")
        df = pd.merge_asof(df.sort_values("start_time"), liquidity, on="start_time", direction="backward")
        df["liquidity_score"] = df["liquidity_score"].ffill().fillna(0.0)
        df["spread_pct"] = df["spread_pct"].ffill().fillna(999.0)
        # Nullable BooleanDtype убирает FutureWarning pandas о silent downcasting
        # и сохраняет безопасное правило: неизвестная ликвидность не дает eligibility.
        df["is_eligible"] = df["is_eligible"].astype("boolean").ffill().fillna(False).astype(bool)
    else:
        df["liquidity_score"] = 0.0
        df["spread_pct"] = 999.0
        df["is_eligible"] = False

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


def prepare_feature_matrix(frame: pd.DataFrame | pd.Series) -> pd.DataFrame:
    """Возвращает числовую матрицу признаков без неявного pandas downcast.

    pandas 2.x предупреждает о future-изменении silent downcasting, если fillna()
    вызывается на object-колонках. Для ML-признаков безопаснее явно привести каждую
    колонку к числу, заменить бесконечности и только затем заполнить пропуски.
    """
    if isinstance(frame, pd.Series):
        out = frame[FEATURE_COLUMNS].to_frame().T
    else:
        out = frame[FEATURE_COLUMNS].copy()
    for col in FEATURE_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.replace([float("inf"), float("-inf")], pd.NA).fillna(0.0).astype(float)


def build_ml_dataset(category: str, symbol: str, interval: str, horizon_bars: int = 12) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    df = load_market_frame(category, symbol, interval)
    if df.empty:
        return pd.DataFrame(), pd.Series(dtype=int), df
    df["future_ret"] = df["close"].shift(-horizon_bars) / df["close"] - 1
    threshold = df["atr_pct"].rolling(100).median().fillna(df["atr_pct"].median()) * 0.35
    # Последние horizon_bars строк нельзя маркировать как отрицательный класс: будущая доходность там неизвестна.
    df["target"] = pd.NA
    valid_future = df["future_ret"].notna()
    df.loc[valid_future, "target"] = (df.loc[valid_future, "future_ret"] > threshold.loc[valid_future]).astype(int)
    clean = df.dropna(subset=FEATURE_COLUMNS + ["future_ret", "target"]).copy()
    X = prepare_feature_matrix(clean)
    y = clean["target"].astype(int)
    return X, y, clean
