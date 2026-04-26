from __future__ import annotations


def test_signal_background_rejects_overlap():
    from app.signal_background import SignalAutoRefresher

    runner = SignalAutoRefresher()
    assert runner._run_lock.acquire(blocking=False)
    try:
        result = runner.run_once()
    finally:
        runner._run_lock.release()

    assert result["reason"] == "already_running"
    assert result["skipped"] == 1


def test_signal_background_run_once_full_pipeline(monkeypatch):
    import app.signal_background as sb
    from app.strategies import StrategySignal

    runner = sb.SignalAutoRefresher()
    calls: list[tuple] = []

    monkeypatch.setattr(sb, "select_auto_symbols", lambda category: (["BTCUSDT", "ETHUSDT"], "unit"))

    def fake_sync_market(category, symbol, interval, days):
        calls.append(("market", category, symbol, interval, days))
        return {"candles": 10, "funding_rates": 2, "open_interest": 2}

    def fake_sync_sentiment(symbols, days, use_llm, category, interval):
        calls.append(("sentiment", tuple(symbols), days, use_llm, category, interval))
        return {"ok": True}

    def fake_build(category, symbol, interval):
        calls.append(("build", category, symbol, interval))
        return [StrategySignal("donchian_atr_breakout", "long", 0.7, 100.0, 98.0, 104.0, 1.0, {}, None)]

    def fake_persist(category, symbol, interval, signals):
        calls.append(("persist", category, symbol, interval, len(signals)))
        return len(signals)

    backtest_requests = []
    llm_requests = []

    monkeypatch.setattr(sb, "sync_market_bundle", fake_sync_market)
    monkeypatch.setattr(sb, "sync_sentiment_bundle", fake_sync_sentiment)
    monkeypatch.setattr(sb, "build_latest_signals", fake_build)
    monkeypatch.setattr(sb, "persist_signals", fake_persist)
    monkeypatch.setattr(sb.background_backtester, "request_run", lambda: backtest_requests.append(True))
    monkeypatch.setattr(sb.background_evaluator, "request_run", lambda: llm_requests.append(True))

    result = runner.run_once()

    assert result["queued"] == 2
    assert result["signals_built"] == 2
    assert result["signals_upserted"] == 2
    assert result["failed"] == 0
    assert result["downstream_requested"] == {"backtest": True, "llm": True}
    assert backtest_requests == [True]
    assert llm_requests == [True]
    call_names = [c[0] for c in calls]
    assert call_names[:2] == ["market", "market"]
    assert call_names.index("sentiment") > call_names.index("market")
    assert call_names.count("persist") == 2


def test_select_auto_symbols_falls_back_to_defaults(monkeypatch):
    import app.signal_background as sb

    monkeypatch.setattr(sb, "build_universe", lambda *args, **kwargs: {"symbols": []})
    monkeypatch.setattr(sb, "latest_universe", lambda *args, **kwargs: [])

    symbols, source = sb.select_auto_symbols("linear")

    assert source == "default_symbols_fallback"
    assert symbols
    assert all(s == s.upper() for s in symbols)
