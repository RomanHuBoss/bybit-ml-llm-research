from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd


def _frame(last_time: datetime) -> pd.DataFrame:
    periods = 260
    start = last_time - timedelta(minutes=15 * (periods - 1))
    rows = []
    for i in range(periods):
        price = 100.0 + i * 0.01
        rows.append(
            {
                "start_time": start + timedelta(minutes=15 * i),
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 10_000,
                "turnover": 1_000_000,
                "atr_14": 1.0,
                "spread_pct": 0.01,
                "liquidity_score": 10.0,
                "is_eligible": True,
                "ema_20": price + 1,
                "ema_50": price,
                "ema_200": price - 1,
                "rsi_14": 48.0,
                "sentiment_score": 0.1,
                "micro_sentiment_score": 0.1,
                "donchian_high": price - 5,
                "donchian_low": price - 20,
                "volume_z": 2.0,
                "ema20_50_gap": 0.01,
                "bb_position": 0.5,
                "bb_width": 0.1,
                "funding_rate": 0.0,
                "oi_change_24": 0.0,
                "ret_12": 0.0,
            }
        )
    return pd.DataFrame(rows)


def test_build_latest_signals_blocks_stale_last_bar(monkeypatch):
    import app.strategies as strategies

    stale_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(strategies, "load_market_frame", lambda *args, **kwargs: _frame(stale_time))

    assert strategies.build_latest_signals("linear", "BTCUSDT", "15") == []


def test_build_latest_signals_allows_recent_closed_bar(monkeypatch):
    import app.strategies as strategies

    now = datetime.now(timezone.utc)
    recent_closed_bar_start = now - timedelta(minutes=35)
    monkeypatch.setattr(strategies, "load_market_frame", lambda *args, **kwargs: _frame(recent_closed_bar_start))

    signals = strategies.build_latest_signals("linear", "BTCUSDT", "15")

    assert signals
    assert all(signal.bar_time is not None for signal in signals)
