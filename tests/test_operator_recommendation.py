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


def test_operator_action_keeps_unqualified_setup_as_research_candidate():
    decision = classify_operator_action(base_row())

    assert decision["operator_action"] == "RESEARCH_CANDIDATE"
    assert decision["operator_level"] == "research"
    assert decision["quality_status"] == "RESEARCH"
    assert any(item["code"] == "strategy_research" for item in decision["operator_evidence_notes"])
    assert any(item["code"] == "backtest_missing" for item in decision["operator_evidence_notes"])
    assert any(item["code"] == "ml_missing" for item in decision["operator_evidence_notes"])
    assert decision["operator_hard_reasons"] == []


def test_operator_action_allows_review_only_for_approved_strategy_quality():
    decision = classify_operator_action(
        base_row(
            trades_count=64,
            profit_factor=1.42,
            max_drawdown=0.08,
            total_return=0.14,
            walk_forward_pass_rate=0.75,
            walk_forward_windows=4,
            quality_status="APPROVED",
            quality_score=84,
            evidence_grade="APPROVED",
            quality_reason="approved by strategy quality",
        )
    )

    assert decision["operator_action"] == "REVIEW_ENTRY"
    assert decision["operator_level"] == "review"
    assert decision["quality_status"] == "APPROVED"
    assert decision["operator_score"] >= 56
    assert any(item["code"] == "strategy_approved" for item in decision["operator_evidence_notes"])


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


def test_operator_action_blocks_directionally_inverted_levels_even_if_absolute_rr_looks_ok():
    decision = classify_operator_action(base_row(direction="long", stop_loss=104.0, take_profit=96.0))

    assert decision["operator_action"] == "NO_TRADE"
    assert any(item["code"] == "levels_order" for item in decision["operator_hard_reasons"])


def test_operator_action_blocks_short_with_long_ordered_levels():
    decision = classify_operator_action(base_row(direction="short", stop_loss=98.0, take_profit=104.0))

    assert decision["operator_action"] == "NO_TRADE"
    assert any(item["code"] == "levels_order" for item in decision["operator_hard_reasons"])


def test_operator_action_blocks_string_mtf_veto_from_json_boundary():
    decision = classify_operator_action(base_row(mtf_veto="true", higher_tf_conflict="true", mtf_status="weak_alignment"))

    assert decision["operator_action"] == "NO_TRADE"
    assert any(item["code"] == "mtf" for item in decision["operator_hard_reasons"])


def test_operator_action_does_not_treat_string_false_as_mtf_veto():
    decision = classify_operator_action(base_row(mtf_veto="false", higher_tf_conflict="false", mtf_status="aligned_bias"))

    assert decision["operator_action"] == "RESEARCH_CANDIDATE"
    assert not any(item["code"] == "mtf" for item in decision["operator_hard_reasons"])


def test_operator_action_treats_no_loss_backtest_as_evidence_not_missing():
    decision = classify_operator_action(base_row(trades_count=12, profit_factor=None, win_rate=1.0))

    assert decision["operator_action"] == "RESEARCH_CANDIDATE"
    assert any(item["code"] == "backtest_no_losses" for item in decision["operator_evidence_notes"])
    assert not any(item["code"] == "backtest_missing" for item in decision["operator_evidence_notes"])


def test_operator_action_blocks_stale_strategy_quality_even_if_row_says_approved():
    from datetime import datetime, timedelta, timezone

    decision = classify_operator_action(
        base_row(
            trades_count=80,
            profit_factor=1.50,
            max_drawdown=0.05,
            total_return=0.12,
            walk_forward_pass_rate=0.75,
            walk_forward_windows=4,
            last_backtest_at=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            quality_status="APPROVED",
            quality_score=90,
        )
    )

    assert decision["operator_action"] == "NO_TRADE"
    assert decision["quality_status"] == "STALE"
    assert any(item["code"] == "strategy_stale" for item in decision["operator_hard_reasons"])
    assert decision["operator_trust_status"] == "BLOCKED"
