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
    from dataclasses import replace

    import app.signal_background as sb
    from types import SimpleNamespace

    runner = sb.SignalAutoRefresher()
    calls: list[tuple] = []

    monkeypatch.setattr(sb, "settings", replace(sb.settings, signal_auto_intervals=("60", "240")))
    monkeypatch.setattr(sb, "select_auto_symbols", lambda category: (["BTCUSDT", "ETHUSDT"], "unit"))

    def fake_sync_market(category, symbol, interval, days):
        calls.append(("market", category, symbol, interval, days))
        return {"candles": 10, "funding_rates": 2, "open_interest": 2}

    def fake_sync_sentiment(symbols, days, intervals, use_llm, category):
        calls.append(("sentiment", tuple(symbols), days, tuple(intervals), use_llm, category))
        return {"ok": True, "intervals": list(intervals)}

    def fake_build(category, symbol, interval):
        calls.append(("build", category, symbol, interval))
        return [SimpleNamespace(strategy="donchian_atr_breakout", direction="long", confidence=0.7, entry=100.0, stop_loss=98.0, take_profit=104.0, atr=1.0, rationale={}, bar_time=None)]

    def fake_persist(category, symbol, interval, signals):
        calls.append(("persist", category, symbol, interval, len(signals)))
        return len(signals)

    backtest_requests = []
    llm_requests = []

    monkeypatch.setattr(sb, "sync_market_bundle", fake_sync_market)
    monkeypatch.setattr(sb, "sync_sentiment_bundle_multi", fake_sync_sentiment)
    monkeypatch.setattr(sb, "build_latest_signals", fake_build)
    monkeypatch.setattr(sb, "persist_signals", fake_persist)
    monkeypatch.setattr(sb.background_backtester, "request_run", lambda: backtest_requests.append(True))
    monkeypatch.setattr(sb.background_evaluator, "request_run", lambda: llm_requests.append(True))

    result = runner.run_once()

    assert result["queued"] == 4
    assert result["market_synced"] == 4
    assert result["intervals"] == ["60", "240"]
    assert result["signals_built"] == 4
    assert result["signals_upserted"] == 4
    assert result["failed"] == 0
    assert result["downstream_requested"] == {"backtest": True, "llm": True}
    assert backtest_requests == [True]
    assert llm_requests == [True]
    call_names = [c[0] for c in calls]
    assert call_names[:4] == ["market", "market", "market", "market"]
    assert call_names.index("sentiment") > call_names.index("market")
    assert call_names.count("persist") == 4
    assert {c[3] for c in calls if c[0] == "market"} == {"60", "240"}


def test_select_auto_symbols_falls_back_to_defaults(monkeypatch):
    import app.signal_background as sb

    monkeypatch.setattr(sb, "build_universe", lambda *args, **kwargs: {"symbols": []})
    monkeypatch.setattr(sb, "latest_universe", lambda *args, **kwargs: [])

    symbols, source = sb.select_auto_symbols("linear")

    assert source == "default_symbols_fallback"
    assert symbols
    assert all(s == s.upper() for s in symbols)
