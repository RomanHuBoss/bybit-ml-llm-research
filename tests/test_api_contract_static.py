from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_latest_signals_api_is_category_scoped_and_not_mixing_markets():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert "def latest_signals(limit: int = 50, entry_only: bool = True, category: str = settings.default_category)" in api
    assert "category = normalize_category(category)" in api
    assert "WHERE category=%s AND interval = ANY(%s)" in api
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
