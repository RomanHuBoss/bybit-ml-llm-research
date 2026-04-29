from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd


def _candles(now: datetime, rows: int = 260) -> pd.DataFrame:
    start = now - timedelta(minutes=15 * (rows - 1))
    times = [start + timedelta(minutes=15 * i) for i in range(rows)]
    base = pd.Series(range(rows), dtype="float64")
    close = 100 + base * 0.1
    return pd.DataFrame(
        {
            "start_time": times,
            "open": close - 0.05,
            "high": close + 0.20,
            "low": close - 0.20,
            "close": close,
            "volume": 1000 + base,
            "turnover": (1000 + base) * close,
        }
    )


def test_load_market_frame_marks_stale_liquidity_as_unknown(monkeypatch):
    from app import features

    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    candles = _candles(now)
    stale_snapshot = pd.DataFrame(
        {
            "liquidity_captured_at": [now - timedelta(hours=4)],
            "liquidity_score": [9.0],
            "spread_pct": [0.01],
            "is_eligible": [True],
        }
    )

    def fake_query_df(sql, params):
        if "FROM candles" in sql:
            return candles.copy()
        if "FROM liquidity_snapshots" in sql:
            return stale_snapshot.copy()
        return pd.DataFrame()

    monkeypatch.setattr(features, "query_df", fake_query_df)

    frame = features.load_market_frame("linear", "BTCUSDT", "15", limit=300)
    last = frame.iloc[-1]

    assert last["liquidity_state"] == "unknown"
    assert last["is_eligible"] is False or bool(last["is_eligible"]) is False
    assert float(last["spread_pct"]) == 999.0
    assert float(last["liquidity_score"]) == 0.0
    assert float(last["liquidity_age_minutes"]) >= 240.0


def test_load_market_frame_keeps_fresh_liquidity_snapshot(monkeypatch):
    from app import features

    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    candles = _candles(now)
    fresh_snapshot = pd.DataFrame(
        {
            "liquidity_captured_at": [now - timedelta(minutes=20)],
            "liquidity_score": [8.5],
            "spread_pct": [0.02],
            "is_eligible": [True],
        }
    )

    def fake_query_df(sql, params):
        if "FROM candles" in sql:
            return candles.copy()
        if "FROM liquidity_snapshots" in sql:
            return fresh_snapshot.copy()
        return pd.DataFrame()

    monkeypatch.setattr(features, "query_df", fake_query_df)

    frame = features.load_market_frame("linear", "BTCUSDT", "15", limit=300)
    last = frame.iloc[-1]

    assert last["liquidity_state"] == "known"
    assert bool(last["is_eligible"]) is True
    assert float(last["spread_pct"]) == 0.02
    assert float(last["liquidity_score"]) == 8.5
