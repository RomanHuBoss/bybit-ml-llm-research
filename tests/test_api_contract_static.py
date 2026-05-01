from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_latest_signals_api_is_category_scoped_and_not_mixing_markets():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert "def latest_signals(limit: int = 50, entry_only: bool = True, category: str = settings.default_category)" in api
    assert "category = normalize_category(category)" in api
    assert "WHERE category=%s AND interval = ANY(%s" in api
    assert '"category": category' in api


def test_api_has_no_duplicate_dead_market_sync_or_backtest_interval_lines():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert api.count("return dict(_sync_market_interval(category, symbol, interval, days, funding_rows) for interval in intervals)") == 1
    assert api.count("interval = normalize_interval(req.interval)") == 1


def test_latest_signals_and_rank_use_symbol_scoped_fresh_liquidity_snapshot():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
    research = (ROOT / "app" / "research.py").read_text(encoding="utf-8")
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")

    for source in (api, research):
        assert "SELECT DISTINCT ON (l.symbol)" in source
        assert "liquidity_snapshot_max_age_minutes" in source
        assert "liquidity_status" in source
        assert "latest_liq_time" not in source
        assert "MAX(captured_at) AS captured_at FROM liquidity_snapshots" not in source

    assert "trend_continuation_setup" in api
    assert "LIQUIDITY_SNAPSHOT_MAX_AGE_MINUTES" in config


def test_symbol_universe_uses_symbol_scoped_fresh_liquidity_snapshot():
    symbols = (ROOT / "app" / "symbols.py").read_text(encoding="utf-8")

    assert "SELECT DISTINCT ON (l.symbol)" in symbols
    assert "liquidity_snapshot_max_age_minutes" in symbols
    assert "liquidity_status" in symbols
    assert "MAX(captured_at)" not in symbols


def test_api_exposes_strategy_lab_and_trading_desk_diagnostics():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
    strategy_lab = (ROOT / "app" / "strategy_lab.py").read_text(encoding="utf-8")

    assert '"/strategies/lab"' in api
    assert '"/trading-desk/diagnostics"' in api
    assert "strategy_lab_snapshot" in api
    assert "trading_desk_diagnostics" in api
    assert "blocker_counts" in strategy_lab
    assert "near_approval" in strategy_lab


def test_signal_build_endpoint_is_parallelized_and_reports_job_count():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert "jobs = [(symbol, interval) for symbol in symbols for interval in intervals]" in api
    assert "thread_name_prefix=\"api-signal-build\"" in api
    assert '"workers": workers' in api
    assert '"jobs": len(jobs)' in api


def test_latest_signals_operator_endpoint_joins_strategy_quality_and_backtest_evidence():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert "latest_backtests AS" in api
    assert "latest_quality AS" in api
    assert "FROM strategy_quality" in api
    assert "LEFT JOIN latest_quality q ON q.symbol=s.symbol AND q.interval=s.interval AND q.strategy=s.strategy" in api
    assert "q.quality_status" in api
    assert "q.quality_score" in api
    assert "q.walk_forward_pass_rate" in api
    assert "b.trades_count" in api
    assert "AS research_score" in api


def test_manual_background_run_endpoints_force_start_workers():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert "signal_refresher.start(force=True)" in api
    assert "background_backtester.start(force=True)" in api
    assert "background_evaluator.start(force=True)" in api
    assert api.count('"accepted": True') >= 3


def test_status_endpoint_degrades_instead_of_crashing_when_db_is_unavailable(monkeypatch):
    import app.api as api

    def broken_fetch_one(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(api, "fetch_one", broken_fetch_one)

    payload = api.status()

    assert payload["ok"] is False
    assert "db unavailable" in payload["db_error"]
    assert payload["candles"] == 0


def test_trading_read_endpoints_degrade_to_diagnostic_payloads(monkeypatch):
    import app.api as api

    def broken(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(api, "latest_universe", broken)
    monkeypatch.setattr(api, "latest_liquidity", broken)
    monkeypatch.setattr(api, "_sentiment_summary", broken)
    monkeypatch.setattr(api, "rank_candidates_multi", broken)
    monkeypatch.setattr(api, "latest_strategy_quality", broken)
    monkeypatch.setattr(api, "quality_summary", broken)
    monkeypatch.setattr(api, "strategy_lab_snapshot", broken)
    monkeypatch.setattr(api, "latest_evaluations", broken)
    monkeypatch.setattr(api, "fetch_all", broken)

    assert api.api_latest_universe()["ok"] is False
    assert api.api_latest_universe()["items"] == []
    assert api.api_latest_liquidity()["ok"] is False
    assert api.api_latest_liquidity()["items"] == []
    assert api.api_sentiment_summary()["ok"] is False
    assert api.api_sentiment_summary()["result"]["items"] == []
    assert api.api_rank_candidates()["ok"] is False
    assert api.api_rank_candidates()["items"] == []
    assert api.api_strategy_quality()["ok"] is False
    assert api.api_strategy_quality()["items"] == []
    assert api.api_strategy_lab()["ok"] is False
    assert api.api_strategy_lab()["items"] == []
    assert api.api_trading_desk_diagnostics()["ok"] is False
    assert api.api_trading_desk_diagnostics()["items"] == []
    assert api.api_llm_evaluations_latest()["ok"] is False
    assert api.api_llm_evaluations_latest()["items"] == []
    assert api.latest_equity()["ok"] is False
    assert api.latest_equity()["runs"] == []
    assert api.latest_news()["ok"] is False
    assert api.latest_news()["news"] == []
    assert api.latest_signals()["ok"] is False
    assert api.latest_signals()["signals"] == []


def test_trading_read_endpoints_do_not_raise_http_500_for_db_read_failures():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    for endpoint in [
        "def api_latest_liquidity",
        "def api_latest_universe",
        "def api_sentiment_summary",
        "def latest_signals",
        "def api_rank_candidates",
        "def api_strategy_quality",
        "def api_strategy_lab",
        "def api_trading_desk_diagnostics",
        "def api_llm_evaluations_latest",
        "def latest_equity",
        "def latest_news",
    ]:
        start = api.index(endpoint)
        stop_candidates = [api.find("\n\n@router.", start + 1), api.find("\ndef ", start + 1)]
        stop_candidates = [x for x in stop_candidates if x != -1]
        stop = min(stop_candidates) if stop_candidates else len(api)
        block = api[start:stop]
        assert "except Exception as exc:" in block
        assert '"ok": False' in block
