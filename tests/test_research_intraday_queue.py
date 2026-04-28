from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _row(symbol: str, interval: str, direction: str, confidence: float, score: float = 0.5) -> dict:
    return {
        "id": abs(hash((symbol, interval, direction, confidence))) % 100000,
        "created_at": datetime.now(timezone.utc),
        "bar_time": datetime.now(timezone.utc) - timedelta(minutes=30),
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "strategy": "regime_adaptive_combo",
        "direction": direction,
        "confidence": confidence,
        "entry": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "sentiment_score": 0.0,
        "rationale": {},
        "total_return": 0.1,
        "max_drawdown": 0.1,
        "sharpe": 1.2,
        "win_rate": 0.55,
        "profit_factor": 1.4,
        "trades_count": 30,
        "roc_auc": 0.58,
        "precision_score": 0.55,
        "recall_score": 0.5,
        "liquidity_score": 7.0,
        "spread_pct": 0.01,
        "turnover_24h": 100_000_000,
        "open_interest_value": 50_000_000,
        "is_eligible": True,
        "research_score": score,
    }


def test_rank_candidates_returns_only_15m_entry_recommendations(monkeypatch):
    import app.research as research

    captured = {}

    def fake_fetch_all(sql, params):
        captured["params"] = params
        return [
            _row("BTCUSDT", "15", "long", 0.70),
            _row("BTCUSDT", "60", "long", 0.64),
            _row("BTCUSDT", "240", "long", 0.58),
        ]

    monkeypatch.setattr(research, "fetch_all", fake_fetch_all)

    out = research.rank_candidates_multi("linear", ["15", "60", "240"], limit=10)

    assert [item["interval"] for item in out] == ["15"]
    assert out[0]["mtf_is_entry_candidate"] is True
    assert out[0]["mtf_bias"]["interval"] == "60"
    assert out[0]["mtf_regime"]["interval"] == "240"
    assert captured["params"][1] == ["15", "60", "240"]


def test_rank_candidates_does_not_promote_60m_to_recommendation(monkeypatch):
    import app.research as research

    monkeypatch.setattr(research, "fetch_all", lambda *_args, **_kwargs: [_row("ETHUSDT", "60", "short", 0.75)])

    assert research.rank_candidates_multi("linear", ["60"], limit=10) == []
