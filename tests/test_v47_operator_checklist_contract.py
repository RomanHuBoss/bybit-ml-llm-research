from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.api import _recommendation_contract_metadata, _recommendation_summary
from app.trade_contract import OPERATOR_CHECKLIST_EXTENSION, enrich_recommendation_row, no_trade_decision_snapshot
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 5, 15, 0, tzinfo=timezone.utc)


def test_v47_nested_recommendation_contains_identity_and_server_checklist() -> None:
    item = enrich_recommendation_row(
        base_row(
            id=4701,
            category="linear",
            symbol="BTCUSDT",
            interval="15",
            strategy="trend_continuation_setup",
            operator_action="REVIEW_ENTRY",
            entry=100.0,
            stop_loss=97.0,
            take_profit=106.0,
            last_price=100.02,
            atr=1.0,
            bar_time="2026-05-05T14:45:00+00:00",
            created_at="2026-05-05T14:46:00+00:00",
            expires_at="2026-05-05T16:00:00+00:00",
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert contract["category"] == "linear"
    assert contract["symbol"] == "BTCUSDT"
    assert contract["interval"] == "15"
    assert contract["strategy"] == "trend_continuation_setup"
    assert contract["bar_time"] == "2026-05-05T14:45:00+00:00"
    assert OPERATOR_CHECKLIST_EXTENSION in contract["compatible_extensions"]
    assert contract["operator_checklist"]
    assert {row["key"] for row in contract["operator_checklist"]} >= {"server_final_gate", "identity", "price_gate", "risk_reward"}
    assert all(row["status"] in {"pass", "warn", "fail"} for row in contract["operator_checklist"])
    assert contract["contract_health"]["ok"] is True


def test_v47_no_trade_snapshot_has_operator_checklist() -> None:
    snapshot = no_trade_decision_snapshot(reason="Нет активных сетапов", category="linear", as_of=NOW)

    assert snapshot["trade_direction"] == "no_trade"
    assert snapshot["symbol"] is None
    assert snapshot["operator_checklist"][0]["key"] == "no_active_recommendation"
    assert snapshot["contract_health"]["ok"] is True


def test_v47_metadata_schema_and_frontend_publish_server_checklist_contract() -> None:
    metadata = _recommendation_contract_metadata()
    summary = _recommendation_summary([])
    frontend = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260505_v47_operator_checklist_contract.sql").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")

    assert metadata["integrity_audit_view"] == "v_recommendation_integrity_audit_v47"
    assert "operator_checklist" in metadata["required_recommendation_fields"]
    assert summary["ui_contract_extension"] == OPERATOR_CHECKLIST_EXTENSION
    assert OPERATOR_CHECKLIST_EXTENSION in summary["compatible_extensions"]
    assert "function serverChecklistFor" in frontend
    assert "serverChecklist.length" in frontend
    assert "Серверный чек-лист" in frontend
    for source in (migration, schema):
        assert "v_recommendation_integrity_audit_v47" in source
        assert "v_recommendation_contract_v47" in source
        assert "operator_checklist_v47" in source
        assert "nested_identity_required" in source
