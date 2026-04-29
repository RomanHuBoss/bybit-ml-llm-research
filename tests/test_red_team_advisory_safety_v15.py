from __future__ import annotations

from pathlib import Path


def _base_signal(**overrides):
    row = {
        "category": "linear",
        "symbol": "BTCUSDT",
        "interval": "15",
        "strategy": "unit",
        "direction": "long",
        "fresh": True,
        "data_status": "fresh",
        "mtf_status": "aligned_intraday",
        "mtf_score": 0.9,
        "confidence": 0.72,
        "entry": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "research_score": 0.8,
        "is_eligible": True,
        "spread_pct": 0.01,
        "profit_factor": 1.6,
        "trades_count": 40,
        "max_drawdown": 0.03,
        "roc_auc": 0.6,
    }
    row.update(overrides)
    return row


def test_unknown_liquidity_cannot_be_review_entry_when_liquidity_required():
    from app.recommendation import classify_operator_action

    decision = classify_operator_action(_base_signal(is_eligible=None, spread_pct=None))

    assert decision["operator_action"] == "WAIT"
    assert decision["operator_level"] == "watch"
    assert any(item["code"] == "liquidity_unknown" for item in decision["operator_warnings"])


def test_confirmed_liquidity_can_still_reach_review_entry():
    from app.recommendation import classify_operator_action

    decision = classify_operator_action(_base_signal())

    assert decision["operator_action"] == "REVIEW_ENTRY"
    assert decision["operator_level"] == "review"


def test_latest_signals_api_contract_includes_liquidity_join_for_operator_decision():
    source = Path("app/api.py").read_text(encoding="utf-8")

    assert "latest_liq_raw" in source
    assert "SELECT DISTINCT ON (l.symbol)" in source
    assert "liquidity_snapshot_max_age_minutes" in source
    assert "l.liquidity_score, l.spread_pct" in source
    assert "l.turnover_24h, l.open_interest_value, l.is_eligible" in source
    assert "l.liquidity_captured_at, l.liquidity_status" in source


def test_frontend_directional_risk_reward_does_not_show_absolute_rr_for_bad_levels():
    source = Path("frontend/app.js").read_text(encoding="utf-8")

    assert "function levelsProblem" in source
    assert "if (levelsProblem(s)) return null" in source
    assert "long_levels_not_ordered" in source
    assert "short_levels_not_ordered" in source
