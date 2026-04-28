from __future__ import annotations

from app.recommendation import classify_operator_action


def base_row(**overrides):
    row = {
        "symbol": "BTCUSDT",
        "interval": "15",
        "direction": "long",
        "confidence": 0.66,
        "entry": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "fresh": True,
        "data_status": "fresh",
        "mtf_status": "aligned_bias",
        "mtf_score": 0.82,
        "mtf_veto": False,
        "higher_tf_conflict": False,
        "is_eligible": True,
        "spread_pct": 0.02,
        "research_score": 0.42,
        "trades_count": None,
        "profit_factor": None,
        "roc_auc": None,
        "ml_probability": None,
    }
    row.update(overrides)
    return row


def test_operator_action_allows_manual_review_without_finished_ml_or_backtest():
    decision = classify_operator_action(base_row())

    assert decision["operator_action"] == "REVIEW_ENTRY"
    assert decision["operator_level"] == "review"
    assert decision["operator_score"] >= 56
    assert any(item["code"] == "backtest_missing" for item in decision["operator_evidence_notes"])
    assert any(item["code"] == "ml_missing" for item in decision["operator_evidence_notes"])
    assert decision["operator_hard_reasons"] == []


def test_operator_action_blocks_higher_timeframe_conflict():
    decision = classify_operator_action(base_row(mtf_veto=True, higher_tf_conflict=True, mtf_status="no_trade_conflict"))

    assert decision["operator_action"] == "NO_TRADE"
    assert any(item["code"] == "mtf" for item in decision["operator_hard_reasons"])


def test_operator_action_blocks_negative_backtest_with_enough_trades():
    decision = classify_operator_action(base_row(trades_count=45, profit_factor=0.82))

    assert decision["operator_action"] == "NO_TRADE"
    assert any(item["code"] == "backtest_negative" for item in decision["operator_hard_reasons"])


def test_operator_action_keeps_moderate_setup_in_wait():
    decision = classify_operator_action(base_row(confidence=0.55, take_profit=102.6))

    assert decision["operator_action"] == "WAIT"
    assert any(item["code"] == "confidence_moderate" for item in decision["operator_warnings"])
