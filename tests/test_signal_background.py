from __future__ import annotations

import sys
import types
from types import SimpleNamespace


def _install_signal_background_fakes(monkeypatch):
    """Keep signal-background unit tests away from real HTTP/LLM/DB-heavy imports."""
    fake_bybit = types.ModuleType("app.bybit_client")

    def _not_configured(*args, **kwargs):  # pragma: no cover - tests monkeypatch concrete call sites
        raise AssertionError("fake dependency call was not monkeypatched")

    fake_bybit.sync_candles = _not_configured
    fake_bybit.sync_funding = _not_configured
    fake_bybit.sync_market_bundle = _not_configured
    fake_bybit.sync_open_interest = _not_configured
    fake_bybit.sync_liquidity_snapshots = _not_configured
    monkeypatch.setitem(sys.modules, "app.bybit_client", fake_bybit)

    fake_backtest = types.ModuleType("app.backtest_background")
    fake_backtest.background_backtester = SimpleNamespace(request_run=lambda: None)
    monkeypatch.setitem(sys.modules, "app.backtest_background", fake_backtest)

    fake_llm = types.ModuleType("app.llm_background")
    fake_llm.background_evaluator = SimpleNamespace(request_run=lambda: None)
    monkeypatch.setitem(sys.modules, "app.llm_background", fake_llm)


def test_signal_background_rejects_overlap(monkeypatch):
    _install_signal_background_fakes(monkeypatch)
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
    _install_signal_background_fakes(monkeypatch)
    from dataclasses import replace

    import app.signal_background as sb

    runner = sb.SignalAutoRefresher()
    calls: list[tuple] = []

    monkeypatch.setattr(sb, "settings", replace(sb.settings, signal_auto_intervals=("60", "240"), market_sync_workers=1, signal_build_workers=1, ml_auto_train_enabled=True, ml_auto_train_max_models_per_cycle=10, ml_auto_train_failure_cooldown_hours=6))
    monkeypatch.setattr(sb, "select_auto_symbols", lambda category: (["BTCUSDT", "ETHUSDT"], "unit"))

    def fake_sync_funding(category, symbol, days):
        calls.append(("funding", category, symbol, days))
        return 2

    def fake_sync_candles(category, symbol, interval, days):
        calls.append(("candles", category, symbol, interval, days))
        return 10

    def fake_sync_open_interest(category, symbol, interval, days):
        calls.append(("open_interest", category, symbol, interval, days))
        return 2

    def fake_sync_sentiment(symbols, days, intervals, use_llm, category):
        calls.append(("sentiment", tuple(symbols), days, tuple(intervals), use_llm, category))
        return {"ok": True, "intervals": list(intervals)}

    def fake_build(category, symbol, interval):
        calls.append(("build", category, symbol, interval))
        return [SimpleNamespace(strategy="donchian_atr_breakout", direction="long", confidence=0.7, entry=100.0, stop_loss=98.0, take_profit=104.0, atr=1.0, rationale={}, bar_time=None)]

    def fake_train_due(category, jobs, horizon_bars, ttl_hours, max_models, failure_cooldown_hours):
        calls.append(("ml_train", category, tuple(jobs), horizon_bars, ttl_hours, max_models, failure_cooldown_hours))
        return {
            "enabled": True,
            "queued": len(jobs),
            "trained": len(jobs),
            "fresh": 0,
            "failed": 0,
            "skipped_limit": 0,
            "skipped_failure_cooldown": 0,
            "items": [{"symbol": symbol, "interval": interval, "status": "trained", "reason": "missing_model_run"} for symbol, interval in jobs],
        }

    def fake_persist(category, symbol, interval, signals):
        calls.append(("persist", category, symbol, interval, len(signals)))
        return len(signals)

    backtest_requests = []
    llm_requests = []

    monkeypatch.setattr(sb, "sync_funding", fake_sync_funding)
    monkeypatch.setattr(sb, "sync_candles", fake_sync_candles)
    monkeypatch.setattr(sb, "sync_open_interest", fake_sync_open_interest)
    monkeypatch.setattr(sb, "sync_sentiment_bundle_multi", fake_sync_sentiment)
    monkeypatch.setattr(sb, "build_latest_signals", fake_build)
    monkeypatch.setattr(sb, "train_due_ml_models", fake_train_due)
    monkeypatch.setattr(sb, "persist_signals", fake_persist)
    monkeypatch.setattr(sb.background_backtester, "request_run", lambda: backtest_requests.append(True))
    monkeypatch.setattr(sb.background_evaluator, "request_run", lambda: llm_requests.append(True))

    result = runner.run_once()

    assert result["queued"] == 4
    assert result["market_synced"] == 4
    assert result["intervals"] == ["60", "240"]
    assert result["signals_built"] == 4
    assert result["signals_upserted"] == 4
    assert result["ml_auto_train"]["trained"] == 4
    assert result["failed"] == 0
    assert result["downstream_requested"] == {"backtest": True, "llm": True}
    assert backtest_requests == [True]
    assert llm_requests == [True]
    call_names = [c[0] for c in calls]
    assert call_names.count("funding") == 2
    assert call_names.count("candles") == 4
    assert call_names.count("open_interest") == 4
    assert call_names.index("sentiment") > call_names.index("candles")
    assert call_names.index("ml_train") > call_names.index("sentiment")
    assert call_names.index("build") > call_names.index("ml_train")
    assert call_names.count("persist") == 4
    assert {c[3] for c in calls if c[0] == "candles"} == {"60", "240"}


def test_select_auto_symbols_falls_back_to_defaults(monkeypatch):
    _install_signal_background_fakes(monkeypatch)
    import app.signal_background as sb

    monkeypatch.setattr(sb, "build_universe", lambda *args, **kwargs: {"symbols": []})
    monkeypatch.setattr(sb, "latest_universe", lambda *args, **kwargs: [])

    symbols, source = sb.select_auto_symbols("linear")

    assert source == "default_symbols_fallback"
    assert symbols
    assert all(s == s.upper() for s in symbols)
