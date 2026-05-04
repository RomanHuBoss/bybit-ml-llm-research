from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.api import _recommendation_contract_metadata
from app.backtest import INTRABAR_EXECUTION_MODEL, SAME_BAR_STOP_FIRST_REASON, _intrabar_exit_reason
from app.recommendation_outcomes import evaluate_signal_outcome
from app.strategy_quality import evaluate_strategy_quality
from app.trade_contract import enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)


def test_v42_backtest_marks_same_bar_sl_tp_as_ambiguous_stop_first_for_long_and_short():
    assert _intrabar_exit_reason("long", high=111.0, low=94.0, stop=95.0, take=110.0) == (SAME_BAR_STOP_FIRST_REASON, 95.0)
    assert _intrabar_exit_reason("short", high=106.0, low=88.0, stop=105.0, take=90.0) == (SAME_BAR_STOP_FIRST_REASON, 105.0)
    assert _intrabar_exit_reason("long", high=111.0, low=98.0, stop=95.0, take=110.0) == ("take_profit", 110.0)


def test_v42_recommendation_outcome_notes_expose_conservative_intrabar_model():
    signal = base_row(direction="short", entry=100.0, stop_loss=105.0, take_profit=90.0, bar_time="2026-05-04T10:00:00+00:00")
    candles = [{"start_time": "2026-05-04T10:15:00+00:00", "high": 106.0, "low": 88.0}]

    outcome = evaluate_signal_outcome(signal, candles, now=NOW)

    assert outcome["outcome_status"] == "hit_stop_loss"
    assert outcome["realized_r"] == -1.0
    assert outcome["notes"]["ambiguous_exit"] is True
    assert outcome["notes"]["exit_reason"] == SAME_BAR_STOP_FIRST_REASON
    assert outcome["notes"]["intrabar_execution_model"] == INTRABAR_EXECUTION_MODEL


def test_v42_strategy_quality_blocks_approval_when_same_bar_ambiguity_is_high():
    quality = evaluate_strategy_quality(
        {
            "trades_count": 80,
            "profit_factor": 1.90,
            "max_drawdown": 0.04,
            "total_return": 0.18,
            "walk_forward_pass_rate": 0.90,
            "walk_forward_windows": 6,
            "ambiguous_exit_count": 24,
            "ambiguous_exit_rate": 0.30,
            "exit_reason_counts": {SAME_BAR_STOP_FIRST_REASON: 24, "take_profit": 56},
        }
    )

    assert quality["quality_status"] != "APPROVED"
    assert quality["evidence_grade"] == "INTRABAR_UNCERTAINTY"
    assert quality["quality_diagnostics"]["ambiguous_exit_rate"] == 0.30


def test_v42_enriched_contract_and_frontend_expose_intrabar_policy():
    item = enrich_recommendation_row(
        base_row(
            entry=100,
            stop_loss=96,
            take_profit=108,
            last_price=100.05,
            atr=1,
            bar_time="2026-05-04T11:45:00+00:00",
            expires_at="2026-05-04T13:00:00+00:00",
            operator_action="REVIEW_ENTRY",
            outcome_status="hit_stop_loss",
            outcome_notes={"ambiguous_exit": True, "exit_reason": SAME_BAR_STOP_FIRST_REASON},
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert contract["intrabar_execution_model"] == INTRABAR_EXECUTION_MODEL
    assert contract["same_bar_stop_first_reason"] == SAME_BAR_STOP_FIRST_REASON
    assert contract["outcome"]["is_ambiguous_intrabar_exit"] is True
    assert contract["signal_breakdown"]["execution_model"]["intrabar"] == INTRABAR_EXECUTION_MODEL

    metadata = _recommendation_contract_metadata()
    assert "intrabar_execution_model" in metadata["required_recommendation_fields"]
    assert "same-bar SL/TP" in metadata["intrabar_execution_policy"]

    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260504_v42_intrabar_stop_first_quality.sql").read_text(encoding="utf-8")

    assert "is_ambiguous_intrabar_exit" in js
    assert "SL-first" in js
    assert ".outcome-contract.ambiguous" in css
    assert "v_intrabar_execution_quality_v42" in migration
    assert "v_backtest_intrabar_execution_quality_v42" in migration
