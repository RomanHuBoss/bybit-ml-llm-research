from __future__ import annotations

import time
from pathlib import Path

import app.strategy_quality as sq
from app.strategy_quality_background import StrategyQualityRefreshService


ROOT = Path(__file__).resolve().parents[1]


def test_strategy_quality_refresh_respects_time_budget(monkeypatch):
    rows = [
        {
            "backtest_run_id": 1,
            "last_backtest_at": None,
            "category": "linear",
            "symbol": "BTCUSDT",
            "interval": "15",
            "strategy": "trend_continuation_setup",
            "total_return": 0.1,
            "max_drawdown": 0.05,
            "sharpe": 1.2,
            "win_rate": 0.55,
            "profit_factor": 1.4,
            "trades_count": 80,
            "equity_curve": [],
        }
    ]
    called = []
    monkeypatch.setattr(sq, "_ensure_strategy_quality_table", lambda: None)
    monkeypatch.setattr(sq, "fetch_all", lambda _sql, _params: rows)
    monkeypatch.setattr(sq, "upsert_strategy_quality_from_run", lambda row: called.append(row) or {"quality_status": sq.APPROVED})

    result = sq.refresh_strategy_quality(limit=1, time_budget_sec=0)

    assert result["partial"] is True
    assert result["updated"] == 0
    assert result["failed"] == 0
    assert called == []


def test_strategy_quality_background_request_is_nonblocking(monkeypatch):
    def fake_refresh(limit, time_budget_sec=None):
        return {"updated": limit, "failed": 0, "partial": False, "time_budget_sec": time_budget_sec}

    monkeypatch.setattr("app.strategy_quality_background.refresh_strategy_quality", fake_refresh)
    service = StrategyQualityRefreshService()

    accepted = service.request_run(3)
    assert accepted["accepted"] is True

    deadline = time.time() + 2
    status = service.status()
    while status["running"] and time.time() < deadline:
        time.sleep(0.01)
        status = service.status()

    assert status["running"] is False
    assert status["last_error"] is None
    assert status["last_result"]["updated"] == 3


def test_frontend_uses_background_quality_refresh_contract():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "/api/strategies/quality/refresh/status" in js
    assert "Strategy quality refresh requested" in js
    assert "scheduleQualityRefreshPoll" in js
    assert "qualityRefreshStatus" in html
    assert "Strategy quality refreshed" not in js
