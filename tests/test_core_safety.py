from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest


def test_ml_dataset_drops_unlabeled_tail(monkeypatch):
    import app.features as features

    periods = 40
    df = pd.DataFrame(
        {
            "start_time": pd.date_range("2024-01-01", periods=periods, freq="h", tz="UTC"),
            "open": [100 + i for i in range(periods)],
            "high": [101 + i for i in range(periods)],
            "low": [99 + i for i in range(periods)],
            "close": [100 + i for i in range(periods)],
            "volume": [1000 + i for i in range(periods)],
            "turnover": [100000 + i for i in range(periods)],
            "atr_pct": [0.01] * periods,
        }
    )
    for col in features.FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0

    monkeypatch.setattr(features, "load_market_frame", lambda *args, **kwargs: df.copy())
    X, y, clean = features.build_ml_dataset("linear", "BTCUSDT", "60", horizon_bars=5)

    assert len(X) == periods - 5
    assert len(y) == periods - 5
    assert clean["future_ret"].notna().all()


def test_strategy_blocks_unknown_liquidity_by_default():
    from app.strategies import donchian_breakout

    row = pd.Series(
        {
            "close": 120.0,
            "atr_14": 2.0,
            "donchian_high": 110.0,
            "ema_20": 115.0,
            "ema_50": 100.0,
            "volume_z": 2.0,
            "micro_sentiment_score": 0.2,
            "spread_pct": 999.0,
            "liquidity_score": 0.0,
            "is_eligible": False,
        }
    )
    assert donchian_breakout(row) is None


def test_position_qty_caps_notional():
    from app.backtest import _position_qty
    from app.config import settings

    qty = _position_qty(equity=10_000, entry=100, stop=99.9)
    assert qty * 100 <= min(settings.max_position_notional_usdt, 10_000 * settings.max_leverage) + 1e-9


def test_backtest_enters_on_next_bar_open_and_persists(monkeypatch):
    import app.backtest as backtest
    from app.strategies import StrategySignal

    n = 310
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    df = pd.DataFrame(
        {
            "start_time": [start + timedelta(hours=i) for i in range(n)],
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
        }
    )
    for col in ["volume", "turnover"]:
        df[col] = 1000.0

    def fake_load_market_frame(*args, **kwargs):
        out = df.copy()
        out["atr_14"] = 1.0
        out["spread_pct"] = 0.01
        out["liquidity_score"] = 8.0
        out["is_eligible"] = True
        return out

    calls = {"insert_batches": []}

    def fake_execute_many_values(sql, rows, page_size=1000):
        materialized = list(rows)
        calls["insert_batches"].append((sql, materialized))
        return len(materialized)

    monkeypatch.setattr(backtest, "load_market_frame", fake_load_market_frame)
    monkeypatch.setattr(backtest, "execute_many_values", fake_execute_many_values)
    monkeypatch.setattr(backtest, "fetch_one", lambda *args, **kwargs: {"id": 42})
    monkeypatch.setitem(
        backtest.STRATEGY_MAP,
        "unit_test_strategy",
        lambda row: StrategySignal("unit_test_strategy", "long", 0.9, 100.0, 99.0, 101.0, 1.0, {}),
    )

    result = backtest.run_backtest("linear", "BTCUSDT", "60", "unit_test_strategy", limit=500)

    trade_batches = [rows for sql, rows in calls["insert_batches"] if "INSERT INTO backtest_trades" in sql]
    assert trade_batches, "ожидалась запись тестовой сделки"
    first_trade = trade_batches[0][0]
    entry_time = first_trade[4]
    assert entry_time == df.iloc[221]["start_time"]
    assert result["run_id"] == 42


def test_validation_rejects_bad_symbol():
    from app.validation import normalize_symbol

    with pytest.raises(ValueError):
        normalize_symbol("BTC/USDT;DROP")


def test_bybit_get_retries_transient_ret_code(monkeypatch):
    from app.bybit_client import BybitClient

    class Response:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

        def json(self):
            return self._payload

    calls = {"n": 0}

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return Response({"retCode": 10006, "retMsg": "rate limit", "result": {}})
        return Response({"retCode": 0, "retMsg": "OK", "result": {"list": []}})

    monkeypatch.setattr("app.bybit_client.requests.get", fake_get)
    monkeypatch.setattr("app.bybit_client.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.bybit_client.random.uniform", lambda *_args, **_kwargs: 0.0)

    assert BybitClient()._get("/v5/market/tickers", {"category": "linear"}) == {"list": []}
    assert calls["n"] == 2
