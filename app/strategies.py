from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .db import execute_many_values
from .features import load_market_frame


@dataclass
class StrategySignal:
    strategy: str
    direction: str
    confidence: float
    entry: float
    stop_loss: float
    take_profit: float
    atr: float
    rationale: dict[str, Any]


def _risk_levels(direction: str, close: float, atr: float, sl_atr: float = 1.8, tp_atr: float = 3.0) -> tuple[float, float]:
    atr = max(float(atr), close * 0.002)
    if direction == "long":
        return close - sl_atr * atr, close + tp_atr * atr
    if direction == "short":
        return close + sl_atr * atr, close - tp_atr * atr
    return close, close


def _market_quality(row: pd.Series) -> tuple[bool, dict[str, Any]]:
    spread = float(row.get("spread_pct", 0) or 0)
    liquidity = float(row.get("liquidity_score", 0) or 0)
    # If no liquidity snapshot exists, do not block the strategy; just report unknown quality.
    if liquidity == 0 and spread == 0:
        return True, {"liquidity_state": "unknown"}
    ok = spread <= 0.08 and liquidity >= 0
    return ok, {"spread_pct": spread, "liquidity_score": liquidity}


def donchian_breakout(row: pd.Series) -> StrategySignal | None:
    ok, quality = _market_quality(row)
    if not ok:
        return None
    close = float(row["close"])
    atr = float(row.get("atr_14", close * 0.01))
    vol_z = float(row.get("volume_z", 0) or 0)
    micro = float(row.get("micro_sentiment_score", 0) or 0)
    if close > float(row.get("donchian_high", np.inf)) and row.get("ema_20", 0) > row.get("ema_50", 0):
        conf = min(0.95, 0.55 + max(vol_z, 0) * 0.05 + max(row.get("ema20_50_gap", 0), 0) * 7 + max(micro, 0) * 0.05)
        sl, tp = _risk_levels("long", close, atr)
        return StrategySignal("donchian_atr_breakout", "long", conf, close, sl, tp, atr, {"reason": "price_breaks_20_bar_high_in_uptrend", "volume_z": vol_z, "micro_sentiment": micro, **quality})
    if close < float(row.get("donchian_low", -np.inf)) and row.get("ema_20", 0) < row.get("ema_50", 0):
        conf = min(0.95, 0.55 + max(vol_z, 0) * 0.05 + max(-row.get("ema20_50_gap", 0), 0) * 7 + max(-micro, 0) * 0.05)
        sl, tp = _risk_levels("short", close, atr)
        return StrategySignal("donchian_atr_breakout", "short", conf, close, sl, tp, atr, {"reason": "price_breaks_20_bar_low_in_downtrend", "volume_z": vol_z, "micro_sentiment": micro, **quality})
    return None


def ema_pullback(row: pd.Series) -> StrategySignal | None:
    ok, quality = _market_quality(row)
    if not ok:
        return None
    close = float(row["close"])
    atr = float(row.get("atr_14", close * 0.01))
    rsi = float(row.get("rsi_14", 50) or 50)
    sentiment = float(row.get("sentiment_score", 0) or 0)
    micro = float(row.get("micro_sentiment_score", 0) or 0)
    if row.get("ema_20", 0) > row.get("ema_50", 0) > row.get("ema_200", 0) and 38 <= rsi <= 55 and close >= row.get("ema_50", 0):
        conf = min(0.9, 0.52 + (55 - rsi) * 0.01 + max(sentiment, 0) * 0.05 + max(micro, 0) * 0.05)
        sl, tp = _risk_levels("long", close, atr, 1.5, 2.7)
        return StrategySignal("ema_pullback_trend", "long", conf, close, sl, tp, atr, {"reason": "pullback_inside_uptrend", "rsi": rsi, "sentiment": sentiment, "micro_sentiment": micro, **quality})
    if row.get("ema_20", 0) < row.get("ema_50", 0) < row.get("ema_200", 0) and 45 <= rsi <= 62 and close <= row.get("ema_50", 0):
        conf = min(0.9, 0.52 + (rsi - 45) * 0.01 + max(-sentiment, 0) * 0.05 + max(-micro, 0) * 0.05)
        sl, tp = _risk_levels("short", close, atr, 1.5, 2.7)
        return StrategySignal("ema_pullback_trend", "short", conf, close, sl, tp, atr, {"reason": "pullback_inside_downtrend", "rsi": rsi, "sentiment": sentiment, "micro_sentiment": micro, **quality})
    return None


def bollinger_rsi_reversion(row: pd.Series) -> StrategySignal | None:
    ok, quality = _market_quality(row)
    if not ok:
        return None
    close = float(row["close"])
    atr = float(row.get("atr_14", close * 0.01))
    rsi = float(row.get("rsi_14", 50) or 50)
    bb_pos = float(row.get("bb_position", 0.5) or 0.5)
    trend_strength = abs(float(row.get("ema20_50_gap", 0) or 0))
    if bb_pos < 0.08 and rsi < 32 and trend_strength < 0.025:
        conf = min(0.88, 0.54 + (32 - rsi) * 0.012)
        sl, tp = _risk_levels("long", close, atr, 1.2, 2.0)
        return StrategySignal("bollinger_rsi_reversion", "long", conf, close, sl, tp, atr, {"reason": "oversold_near_lower_band", "rsi": rsi, "bb_position": bb_pos, **quality})
    if bb_pos > 0.92 and rsi > 68 and trend_strength < 0.025:
        conf = min(0.88, 0.54 + (rsi - 68) * 0.012)
        sl, tp = _risk_levels("short", close, atr, 1.2, 2.0)
        return StrategySignal("bollinger_rsi_reversion", "short", conf, close, sl, tp, atr, {"reason": "overbought_near_upper_band", "rsi": rsi, "bb_position": bb_pos, **quality})
    return None


def volatility_squeeze(row: pd.Series, history: pd.DataFrame) -> StrategySignal | None:
    ok, quality = _market_quality(row)
    if not ok or len(history) < 120:
        return None
    close = float(row["close"])
    atr = float(row.get("atr_14", close * 0.01))
    width = float(row.get("bb_width", 0) or 0)
    width_q20 = float(history["bb_width"].tail(120).quantile(0.2))
    vol_z = float(row.get("volume_z", 0) or 0)
    micro = float(row.get("micro_sentiment_score", 0) or 0)
    if width <= width_q20 and vol_z > 0.5:
        if close > row.get("ema_20", close) and micro > -0.35:
            sl, tp = _risk_levels("long", close, atr, 1.6, 3.2)
            return StrategySignal("volatility_squeeze_breakout", "long", min(0.86, 0.55 + vol_z * 0.06 + max(micro, 0) * 0.06), close, sl, tp, atr, {"reason": "low_bb_width_with_volume_expansion", "bb_width": width, "micro_sentiment": micro, **quality})
        if close < row.get("ema_20", close) and micro < 0.35:
            sl, tp = _risk_levels("short", close, atr, 1.6, 3.2)
            return StrategySignal("volatility_squeeze_breakout", "short", min(0.86, 0.55 + vol_z * 0.06 + max(-micro, 0) * 0.06), close, sl, tp, atr, {"reason": "low_bb_width_with_volume_expansion", "bb_width": width, "micro_sentiment": micro, **quality})
    return None


def funding_contrarian(row: pd.Series) -> StrategySignal | None:
    ok, quality = _market_quality(row)
    if not ok:
        return None
    close = float(row["close"])
    atr = float(row.get("atr_14", close * 0.01))
    funding = float(row.get("funding_rate", 0) or 0)
    rsi = float(row.get("rsi_14", 50) or 50)
    if funding > 0.0008 and rsi > 64:
        sl, tp = _risk_levels("short", close, atr, 1.4, 2.2)
        return StrategySignal("funding_extreme_contrarian", "short", min(0.84, 0.53 + funding * 250 + (rsi - 64) * 0.01), close, sl, tp, atr, {"reason": "crowded_longs_high_funding", "funding_rate": funding, **quality})
    if funding < -0.0008 and rsi < 36:
        sl, tp = _risk_levels("long", close, atr, 1.4, 2.2)
        return StrategySignal("funding_extreme_contrarian", "long", min(0.84, 0.53 + abs(funding) * 250 + (36 - rsi) * 0.01), close, sl, tp, atr, {"reason": "crowded_shorts_negative_funding", "funding_rate": funding, **quality})
    return None


def oi_confirmation(row: pd.Series) -> StrategySignal | None:
    ok, quality = _market_quality(row)
    if not ok:
        return None
    close = float(row["close"])
    atr = float(row.get("atr_14", close * 0.01))
    oi_chg = float(row.get("oi_change_24", 0) or 0)
    ret_12 = float(row.get("ret_12", 0) or 0)
    if oi_chg > 0.025 and ret_12 > 0.015 and row.get("ema_20", 0) > row.get("ema_50", 0):
        sl, tp = _risk_levels("long", close, atr, 1.7, 3.0)
        return StrategySignal("oi_trend_confirmation", "long", min(0.82, 0.54 + oi_chg * 3 + ret_12 * 4), close, sl, tp, atr, {"reason": "price_and_oi_expand_together", "oi_change_24": oi_chg, **quality})
    if oi_chg > 0.025 and ret_12 < -0.015 and row.get("ema_20", 0) < row.get("ema_50", 0):
        sl, tp = _risk_levels("short", close, atr, 1.7, 3.0)
        return StrategySignal("oi_trend_confirmation", "short", min(0.82, 0.54 + oi_chg * 3 + abs(ret_12) * 4), close, sl, tp, atr, {"reason": "downtrend_with_oi_expansion", "oi_change_24": oi_chg, **quality})
    return None


def sentiment_filter(row: pd.Series) -> StrategySignal | None:
    ok, quality = _market_quality(row)
    if not ok:
        return None
    close = float(row["close"])
    atr = float(row.get("atr_14", close * 0.01))
    sentiment = float(row.get("sentiment_score", 0) or 0)
    news = float(row.get("news_sentiment_score", 0) or 0)
    rsi = float(row.get("rsi_14", 50) or 50)
    if sentiment < -0.55 and rsi < 35 and row.get("ema_20", close) >= row.get("ema_50", close) * 0.985:
        sl, tp = _risk_levels("long", close, atr, 1.3, 2.2)
        return StrategySignal("sentiment_fear_reversal", "long", min(0.78, 0.52 + abs(sentiment) * 0.18 + (35 - rsi) * 0.008), close, sl, tp, atr, {"reason": "extreme_fear_plus_technical_exhaustion", "sentiment": sentiment, "news_sentiment": news, **quality})
    if sentiment > 0.65 and rsi > 70:
        sl, tp = _risk_levels("short", close, atr, 1.3, 2.1)
        return StrategySignal("sentiment_greed_reversal", "short", min(0.78, 0.52 + sentiment * 0.16 + (rsi - 70) * 0.008), close, sl, tp, atr, {"reason": "extreme_greed_plus_overbought", "sentiment": sentiment, "news_sentiment": news, **quality})
    return None


def regime_adaptive_combo(latest: pd.Series, history: pd.DataFrame) -> StrategySignal | None:
    signals = [
        donchian_breakout(latest),
        ema_pullback(latest),
        bollinger_rsi_reversion(latest),
        volatility_squeeze(latest, history),
        funding_contrarian(latest),
        oi_confirmation(latest),
        sentiment_filter(latest),
    ]
    signals = [s for s in signals if s is not None]
    if not signals:
        return None
    long_score = sum(s.confidence for s in signals if s.direction == "long")
    short_score = sum(s.confidence for s in signals if s.direction == "short")
    if max(long_score, short_score) < 0.95:
        return None
    direction = "long" if long_score > short_score else "short"
    aligned = [s for s in signals if s.direction == direction]
    best = max(aligned, key=lambda s: s.confidence)
    confidence = min(0.92, 0.50 + max(long_score, short_score) / max(len(signals), 1) * 0.38)
    return StrategySignal(
        "regime_adaptive_combo",
        direction,
        confidence,
        best.entry,
        best.stop_loss,
        best.take_profit,
        best.atr,
        {
            "reason": "multi_strategy_alignment",
            "votes": [{"strategy": s.strategy, "direction": s.direction, "confidence": s.confidence} for s in signals],
            "long_score": long_score,
            "short_score": short_score,
        },
    )


def build_latest_signals(category: str, symbol: str, interval: str, limit: int = 2000) -> list[StrategySignal]:
    df = load_market_frame(category, symbol, interval, limit=limit)
    if df.empty or len(df) < 250:
        return []
    latest = df.iloc[-1]
    history = df.iloc[:-1]
    candidates = [
        donchian_breakout(latest),
        ema_pullback(latest),
        bollinger_rsi_reversion(latest),
        volatility_squeeze(latest, history),
        funding_contrarian(latest),
        oi_confirmation(latest),
        sentiment_filter(latest),
        regime_adaptive_combo(latest, history),
    ]
    return [s for s in candidates if s is not None]


def persist_signals(category: str, symbol: str, interval: str, signals: list[StrategySignal]) -> int:
    rows = []
    for sig in signals:
        rows.append(
            (
                category,
                symbol.upper(),
                interval,
                sig.strategy,
                sig.direction,
                sig.confidence,
                sig.entry,
                sig.stop_loss,
                sig.take_profit,
                sig.atr,
                None,
                sig.rationale.get("sentiment") or sig.rationale.get("micro_sentiment"),
                sig.rationale,
            )
        )
    return execute_many_values(
        """
        INSERT INTO signals(category, symbol, interval, strategy, direction, confidence, entry, stop_loss, take_profit, atr, ml_probability, sentiment_score, rationale)
        VALUES %s
        """,
        rows,
    )
