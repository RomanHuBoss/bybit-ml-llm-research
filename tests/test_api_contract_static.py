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
