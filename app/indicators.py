from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.rolling(period).mean()


def bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid.replace(0, np.nan)
    return lower, mid, upper, width


def donchian(df: pd.DataFrame, period: int = 20) -> tuple[pd.Series, pd.Series]:
    upper = df["high"].rolling(period).max().shift(1)
    lower = df["low"].rolling(period).min().shift(1)
    return lower, upper


def realized_vol(close: pd.Series, period: int = 24) -> pd.Series:
    ret = close.pct_change()
    return ret.rolling(period).std() * np.sqrt(period)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ["open", "high", "low", "close", "volume", "turnover"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.sort_values("start_time").reset_index(drop=True)
    out["ret_1"] = out["close"].pct_change()
    out["ret_3"] = out["close"].pct_change(3)
    out["ret_12"] = out["close"].pct_change(12)
    out["ret_24"] = out["close"].pct_change(24)
    out["ema_20"] = ema(out["close"], 20)
    out["ema_50"] = ema(out["close"], 50)
    out["ema_200"] = ema(out["close"], 200)
    out["rsi_14"] = rsi(out["close"], 14)
    out["atr_14"] = atr(out, 14)
    out["atr_pct"] = out["atr_14"] / out["close"].replace(0, np.nan)
    out["bb_lower"], out["bb_mid"], out["bb_upper"], out["bb_width"] = bollinger(out["close"])
    out["donchian_low"], out["donchian_high"] = donchian(out, 20)
    out["rv_24"] = realized_vol(out["close"], 24)
    out["volume_z"] = (out["volume"] - out["volume"].rolling(48).mean()) / out["volume"].rolling(48).std().replace(0, np.nan)
    return out
