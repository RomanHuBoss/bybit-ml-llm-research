from __future__ import annotations

from pathlib import Path

from app.recommendation import classify_operator_action
from app.trade_contract import enrich_recommendation_row

ROOT = Path(__file__).resolve().parents[1]


def base_row(**overrides):
    row = {
        "id": 777,
        "symbol": "BTCUSDT",
        "category": "linear",
        "interval": "15",
        "strategy": "ema_rsi_breakout",
        "direction": "long",
        "confidence": 0.72,
        "entry": 100.0,
        "stop_loss": 98.0,
        "take_profit": 105.0,
        "atr": 1.2,
        "fresh": True,
        "data_status": "fresh",
        "mtf_status": "aligned_bias",
        "mtf_score": 0.86,
        "mtf_veto": False,
        "higher_tf_conflict": False,
        "is_eligible": True,
        "spread_pct": 0.02,
        "research_score": 0.82,
        "trades_count": 80,
        "profit_factor": 1.55,
        "max_drawdown": 0.08,
        "total_return": 0.18,
        "walk_forward_pass_rate": 0.72,
        "walk_forward_windows": 4,
        "quality_status": "APPROVED",
        "quality_score": 88,
        "evidence_grade": "APPROVED",
        "quality_reason": "approved by strategy quality",
        "roc_auc": 0.61,
        "ml_probability": 0.62,
    }
    row.update(overrides)
    return row


def test_recent_loss_quarantine_blocks_review_entry_even_when_strategy_approved():
    decision = classify_operator_action(
        base_row(
            recent_outcomes_count=8,
            recent_loss_count=7,
            recent_loss_rate=0.875,
            recent_average_r=-0.42,
            recent_profit_factor=0.31,
            recent_consecutive_losses=2,
        )
    )

    assert decision["operator_action"] == "NO_TRADE"
    assert decision["operator_trust_status"] == "BLOCKED"
    assert any(item["code"] == "recent_loss_quarantine" for item in decision["operator_hard_reasons"])
    assert any(item["code"] == "recent_outcome_quality" for item in decision["operator_evidence_notes"])


def test_loss_streak_quarantine_blocks_before_operator_review():
    decision = classify_operator_action(
        base_row(
            recent_outcomes_count=5,
            recent_loss_count=3,
            recent_loss_rate=0.60,
            recent_average_r=-0.08,
            recent_profit_factor=0.85,
            recent_consecutive_losses=3,
        )
    )

    assert decision["operator_action"] == "NO_TRADE"
    assert any(item["code"] == "loss_streak_quarantine" for item in decision["operator_hard_reasons"])


def test_trade_contract_exposes_recent_outcome_quality_for_ui():
    row = base_row(
        recent_outcomes_count=6,
        recent_loss_count=5,
        recent_loss_rate=0.8333333333,
        recent_average_r=-0.35,
        recent_profit_factor=0.42,
        recent_consecutive_losses=2,
    )
    decision = classify_operator_action(row)
    contract = enrich_recommendation_row({**row, **decision})["recommendation"]

    outcome_quality = contract["signal_breakdown"]["outcome_quality"]
    assert outcome_quality["recent_outcomes_count"] == 6
    assert outcome_quality["recent_loss_rate"] == 0.8333333333
    assert "quarantine_rules" in outcome_quality


def test_v43_migration_publishes_recent_loss_audit_views():
    migration = (ROOT / "sql" / "migrations" / "20260504_v43_recent_loss_quarantine.sql").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    for source in (migration, schema):
        assert "v_recommendation_recent_outcome_quality_v43" in source
        assert "v_recommendation_integrity_audit_v43" in source
        assert "recent_loss_quarantine" in source
        assert "loss_streak_quarantine" in source
