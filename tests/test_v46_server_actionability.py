from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.api import _recommendation_contract_metadata, _recommendation_summary
from app.trade_contract import enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 5, 15, 0, tzinfo=timezone.utc)


def test_v46_research_candidate_outside_entry_zone_is_no_trade() -> None:
    item = enrich_recommendation_row(
        base_row(
            operator_action="RESEARCH_CANDIDATE",
            entry=100.0,
            stop_loss=97.0,
            take_profit=106.0,
            last_price=101.0,
            atr=1.0,
            bar_time="2026-05-05T14:45:00+00:00",
            expires_at="2026-05-05T16:00:00+00:00",
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert contract["recommendation_status"] == "missed_entry"
    assert contract["trade_direction"] == "no_trade"
    assert contract["price_status"] == "moved_away"
    assert contract["price_actionability"]["is_price_actionable"] is False
    assert contract["no_trade_reason"] == "price_moved_away"
    assert contract["contract_health"]["ok"] is True


def test_v46_contract_metadata_and_schema_publish_server_actionability() -> None:
    metadata = _recommendation_contract_metadata()
    migration = (ROOT / "sql" / "migrations" / "20260505_v46_server_actionability_and_price_gate.sql").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert metadata["integrity_audit_view"] == "v_recommendation_integrity_audit_v46"
    assert "server_actionability_v46" in metadata["compatible_extensions"]
    for source in (migration, schema):
        assert "v_recommendation_integrity_audit_v46" in source
        assert "v_recommendation_contract_v46" in source
        assert "active_price_outside_entry_zone" in source
        assert "server_actionability_v46" in source
    assert '"v_recommendation_integrity_audit_v46"' in api


def test_v46_summary_exposes_compatible_extension_list() -> None:
    summary = _recommendation_summary([])

    assert summary["ui_contract_extension"] == "server_actionability_v46"
    assert "server_actionability_v46" in summary["compatible_extensions"]
