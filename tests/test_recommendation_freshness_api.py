from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _signal(symbol: str, bar_time: datetime, interval: str = "15", score: float = 0.7) -> dict:
    return {
        "id": hash((symbol, bar_time.isoformat())) % 100000,
        "created_at": datetime.now(timezone.utc),
        "bar_time": bar_time,
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "strategy": "ema_pullback_trend",
        "direction": "long",
        "confidence": 0.74,
        "entry": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "atr": 1.0,
        "ml_probability": None,
        "sentiment_score": 0.1,
        "rationale": {"reason": "unit_test"},
        "research_score": score,
    }


def test_safety_filters_stale_and_missing_bar_time():
    from app.safety import annotate_and_filter_fresh_signals

    now = datetime.now(timezone.utc)
    fresh_start = now - timedelta(minutes=30)
    stale_start = now - timedelta(days=5)
    rows = [
        _signal("BTCUSDT", fresh_start),
        _signal("ETHUSDT", stale_start),
        {**_signal("SOLUSDT", fresh_start), "bar_time": None},
    ]

    filtered = annotate_and_filter_fresh_signals(rows)

    assert [row["symbol"] for row in filtered] == ["BTCUSDT"]
    assert filtered[0]["data_status"] == "fresh"
    assert filtered[0]["risk_reward"] == 2.0


def test_latest_signals_api_suppresses_stale_rows_before_mtf(monkeypatch):
    import app.api as api

    now = datetime.now(timezone.utc)
    stale_start = now - timedelta(days=4)
    fresh_start = now - timedelta(minutes=30)

    monkeypatch.setattr(api, "fetch_all", lambda *args, **kwargs: [_signal("OLDUSDT", stale_start), _signal("BTCUSDT", fresh_start)])
    monkeypatch.setattr(api, "_apply_mtf_consensus", lambda rows, **kwargs: rows)

    result = api.latest_signals(limit=10, entry_only=False)

    assert result["ok"] is True
    assert [row["symbol"] for row in result["signals"]] == ["BTCUSDT"]
    assert result["signals"][0]["fresh"] is True


def test_research_rank_suppresses_stale_rows_before_scoring_output(monkeypatch):
    import app.research as research

    now = datetime.now(timezone.utc)
    rows = [
        _signal("STALEUSDT", now - timedelta(days=3), score=10.0),
        _signal("BTCUSDT", now - timedelta(minutes=30), score=0.1),
    ]
    monkeypatch.setattr(research, "fetch_all", lambda *args, **kwargs: rows)
    monkeypatch.setattr(research, "apply_mtf_consensus", lambda rows, **kwargs: rows)

    result = research.rank_candidates_multi("linear", ["15"], limit=5)

    assert [row["symbol"] for row in result] == ["BTCUSDT"]


def test_latest_signals_api_can_emit_review_entry_when_quality_evidence_is_joined(monkeypatch):
    import app.api as api

    now = datetime.now(timezone.utc)
    row = _signal("BTCUSDT", now - timedelta(minutes=30), score=0.82)
    row.update(
        {
            "is_eligible": True,
            "spread_pct": 0.01,
            "mtf_status": "aligned_bias",
            "mtf_score": 0.84,
            "mtf_veto": False,
            "higher_tf_conflict": False,
            "trades_count": 72,
            "profit_factor": 1.52,
            "max_drawdown": 0.06,
            "total_return": 0.18,
            "win_rate": 0.57,
            "sharpe": 1.15,
            "walk_forward_pass_rate": 0.74,
            "walk_forward_windows": 4,
            "last_backtest_at": now.isoformat(),
            "quality_status": "APPROVED",
            "quality_score": 88,
            "evidence_grade": "APPROVED",
            "quality_reason": "unit-test approved quality row",
        }
    )

    monkeypatch.setattr(api, "ensure_strategy_quality_storage", lambda: None)
    monkeypatch.setattr(api, "fetch_all", lambda *args, **kwargs: [row])
    monkeypatch.setattr(api, "_apply_mtf_consensus", lambda rows, **kwargs: rows)

    result = api.latest_signals(limit=10, entry_only=True)

    assert result["ok"] is True
    assert len(result["signals"]) == 1
    signal = result["signals"][0]
    assert signal["symbol"] == "BTCUSDT"
    assert signal["operator_action"] == "REVIEW_ENTRY"
    assert signal["operator_level"] == "review"
    assert signal["quality_status"] == "APPROVED"
    assert any(item["code"] == "strategy_approved" for item in signal["operator_evidence_notes"])
