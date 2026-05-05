from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.api import _recommendation_contract_metadata
from app.trade_contract import contract_health, enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 5, 14, 0, tzinfo=timezone.utc)


def test_v45_nested_recommendation_contract_contains_trade_levels() -> None:
    item = enrich_recommendation_row(
        base_row(
            entry=100.0,
            stop_loss=96.0,
            take_profit=109.0,
            last_price=100.1,
            atr=1.4,
            bar_time="2026-05-05T13:45:00+00:00",
            expires_at="2026-05-05T16:00:00+00:00",
            operator_action="REVIEW_ENTRY",
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert contract["entry"] == 100.0
    assert contract["stop_loss"] == 96.0
    assert contract["take_profit"] == 109.0
    assert contract["level_validation"] == {"valid": True, "reason": None}
    assert contract["contract_health"]["ok"] is True
    assert contract["price_actionability"]["is_price_actionable"] is True


def test_v45_contract_health_rejects_directional_contract_without_nested_levels() -> None:
    broken = {
        "recommendation_id": 1,
        "recommendation_status": "review_entry",
        "trade_direction": "long",
        "confidence_score": 65,
        "expires_at": "2026-05-05T16:00:00+00:00",
        "risk_pct": 0.04,
        "expected_reward_pct": 0.08,
        "risk_reward": 2.0,
        "net_risk_reward": 1.8,
        "recommendation_explanation": "test",
        "price_actionability": {"is_price_actionable": True, "reason": None},
        "signal_breakdown": {},
        "frontend_may_recalculate": False,
        "decision_source": "server_enriched_contract_v40",
        "is_actionable": True,
    }

    health = contract_health(broken)

    assert health["ok"] is False
    codes = {problem["code"] for problem in health["problems"]}
    assert {"missing_entry", "missing_stop_loss", "missing_take_profit", "missing_levels"} <= codes


def test_v45_contract_metadata_and_migration_publish_extension() -> None:
    metadata = _recommendation_contract_metadata()
    migration = (ROOT / "sql" / "migrations" / "20260505_v45_nested_trade_contract_and_signal_payload.sql").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "nested_trade_levels_v45" in metadata["compatible_extensions"]
    for source in (migration, schema):
        assert "v_recommendation_integrity_audit_v45" in source
        assert "v_recommendation_contract_v45" in source
        assert "ck_signals_rationale_object_v45" in source
        assert "nested_trade_levels_v45" in source
    assert "contract.entry" in frontend
    assert "console.warn" not in frontend
