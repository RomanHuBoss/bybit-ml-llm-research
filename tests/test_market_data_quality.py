from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from app import bybit_client
from app.market_data_quality import candle_problem, clean_market_frame, validate_ohlcv_values


def test_ohlcv_validator_rejects_physically_impossible_candles():
    ok, reason, _values = validate_ohlcv_values(100, 99, 98, 100, 10, 1000)
    assert not ok
    assert reason == "high_below_body"

    ok, reason, _values = validate_ohlcv_values(100, 102, 101, 100, 10, 1000)
    assert not ok
    assert reason == "low_above_body"

    ok, reason, _values = validate_ohlcv_values(100, 105, 95, 102, 0, None)
    assert ok
    assert reason is None

    ok, reason, _values = validate_ohlcv_values(100, 105, 95, 102, "nan", None)
    assert not ok
    assert reason == "non_finite_volume"


def test_clean_market_frame_drops_invalid_and_duplicate_bars():
    t0 = pd.Timestamp("2026-04-29T10:00:00Z")
    raw = pd.DataFrame([
        {"start_time": t0, "open": 100, "high": 105, "low": 95, "close": 101, "volume": 1, "turnover": 100},
        {"start_time": t0 + pd.Timedelta(minutes=15), "open": 100, "high": 99, "low": 95, "close": 98, "volume": 1, "turnover": 100},
        {"start_time": t0, "open": 101, "high": 106, "low": 100, "close": 104, "volume": 2, "turnover": 200},
    ])

    clean = clean_market_frame(raw)

    assert len(clean) == 1
    assert clean.iloc[0]["close"] == 104
    assert candle_problem(clean.iloc[0].to_dict()) is None


def test_sync_candles_skips_unclosed_malformed_and_invalid_api_rows(monkeypatch):
    now = datetime.now(timezone.utc)
    closed = now - timedelta(hours=2)
    unclosed = now
    closed_ms = int(closed.timestamp() * 1000)
    unclosed_ms = int(unclosed.timestamp() * 1000)

    class FakeClient:
        def get_kline(self, *args, **kwargs):
            return [
                [str(closed_ms), "100", "105", "95", "101", "10", "1000"],
                [str(closed_ms + 1), "100", "99", "95", "101", "10", "1000"],
                [str(unclosed_ms), "100", "105", "95", "101", "10", "1000"],
                ["bad-ts", "100", "105", "95", "101", "10", "1000"],
                [str(closed_ms + 2), "100"],
            ]

    persisted = {}

    def fake_execute_many_values(sql, rows, page_size=1000):
        persisted["rows"] = list(rows)
        return len(persisted["rows"])

    monkeypatch.setattr(bybit_client, "BybitClient", FakeClient)
    monkeypatch.setattr(bybit_client, "execute_many_values", fake_execute_many_values)

    inserted = bybit_client.sync_candles("linear", "BTCUSDT", "60", 1)

    assert inserted == 1
    assert len(persisted["rows"]) == 1
    row = persisted["rows"][0]
    assert row[0:3] == ("linear", "BTCUSDT", "60")
    assert row[4:10] == (100.0, 105.0, 95.0, 101.0, 10.0, 1000.0)
