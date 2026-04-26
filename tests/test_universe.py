from __future__ import annotations

from datetime import datetime, timezone


def test_universe_excludes_unverified_core_symbols(monkeypatch):
    import app.symbols as symbols

    now = datetime.now(timezone.utc)
    rows = [
        {"symbol": "BTCUSDT", "captured_at": now, "is_eligible": True, "liquidity_score": 8.5, "spread_pct": 0.01},
        {"symbol": "ETHUSDT", "captured_at": now, "is_eligible": False, "liquidity_score": 8.0, "spread_pct": 0.50},
        {"symbol": "SOLUSDT", "captured_at": now, "is_eligible": True, "liquidity_score": 7.9, "spread_pct": 0.02},
    ]
    monkeypatch.setattr(symbols, "latest_liquidity", lambda category, limit: rows)
    monkeypatch.setattr(symbols, "execute_many_values", lambda sql, data: len(list(data)))

    result = symbols.build_universe("linear", "hybrid", limit=10, refresh=False)

    assert "BTCUSDT" in result["symbols"]
    assert "SOLUSDT" in result["symbols"]
    assert "ETHUSDT" not in result["symbols"]
