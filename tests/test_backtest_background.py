from __future__ import annotations


def test_backtest_background_rejects_overlap():
    from app.backtest_background import BacktestBackgroundRunner

    runner = BacktestBackgroundRunner()
    assert runner._run_lock.acquire(blocking=False)
    try:
        result = runner.run_once()
    finally:
        runner._run_lock.release()

    assert result["reason"] == "already_running"
    assert result["skipped"] == 1


def test_candidates_needing_backtest_uses_staleness_query(monkeypatch):
    import app.backtest_background as bg

    captured = {}

    def fake_fetch_all(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return [
            {
                "category": "linear",
                "symbol": "BTCUSDT",
                "interval": "60",
                "strategy": "donchian_atr_breakout",
            }
        ]

    monkeypatch.setattr(bg, "fetch_all", fake_fetch_all)

    rows = bg.candidates_needing_backtest(limit=3)

    assert rows[0]["symbol"] == "BTCUSDT"
    assert "b.run_id IS NULL" in captured["sql"]
    assert "b.backtest_created_at < s.signal_created_at" in captured["sql"]
    assert "strategy_names" in captured["sql"]
    assert "candle_ok" in captured["sql"]
    assert captured["params"][-1] == 3
    assert "interval = ANY" in captured["sql"]
    assert "15" in captured["params"][1]


def test_backtest_background_run_once_runs_candidates_with_bounded_workers(monkeypatch):
    from dataclasses import replace

    import app.backtest_background as bg

    runner = bg.BacktestBackgroundRunner()
    calls = []
    monkeypatch.setattr(bg, "settings", replace(bg.settings, backtest_auto_workers=1))

    monkeypatch.setattr(
        bg,
        "candidates_needing_backtest",
        lambda limit: [
            {"category": "linear", "symbol": "BTCUSDT", "interval": "60", "strategy": "donchian_atr_breakout"},
            {"category": "linear", "symbol": "ETHUSDT", "interval": "60", "strategy": "ema_pullback_trend"},
        ],
    )

    def fake_run_backtest(category, symbol, interval, strategy, limit):
        calls.append((category, symbol, interval, strategy, limit))
        if symbol == "ETHUSDT":
            raise RuntimeError("not enough candles")
        return {"run_id": 101, "trades_count": 4}

    monkeypatch.setattr(bg, "run_backtest", fake_run_backtest)

    result = runner.run_once()

    assert len(calls) == 2
    assert result["queued"] == 2
    assert result["backtested"] == 1
    assert result["failed"] == 1
    assert result["workers"] == 1
    assert result["items"][0]["run_id"] == 101
    assert result["items"][1]["status"] == "error"
