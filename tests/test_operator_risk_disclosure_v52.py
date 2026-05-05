from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.api import _recommendation_contract_metadata, _recommendation_summary
from app.trade_contract import (
    OPERATOR_RISK_DISCLOSURE_EXTENSION,
    COMPATIBLE_EXTENSIONS,
    enrich_recommendation_row,
    no_trade_decision_snapshot,
)
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 5, 15, 30, tzinfo=timezone.utc)


def _codes(items: list[dict]) -> set[str]:
    return {str(item.get("code")) for item in items if isinstance(item, dict)}


def test_v52_review_entry_contract_discloses_advisory_only_and_confidence_semantics() -> None:
    item = enrich_recommendation_row(
        base_row(
            operator_action="REVIEW_ENTRY",
            entry=100.0,
            stop_loss=97.0,
            take_profit=106.0,
            last_price=100.05,
            last_price_time="2026-05-05T15:20:00+00:00",
            bar_time="2026-05-05T15:15:00+00:00",
            created_at="2026-05-05T15:16:00+00:00",
            expires_at="2026-05-05T16:15:00+00:00",
        ),
        now=NOW,
    )
    contract = item["recommendation"]
    disclosures = contract["operator_risk_disclosures"]
    codes = _codes(disclosures)

    assert OPERATOR_RISK_DISCLOSURE_EXTENSION in COMPATIBLE_EXTENSIONS
    assert OPERATOR_RISK_DISCLOSURE_EXTENSION in contract["compatible_extensions"]
    assert contract["recommendation_status"] == "review_entry"
    assert contract["contract_health"]["ok"] is True
    assert "advisory_only_no_auto_orders" in codes
    assert "confidence_not_win_probability" in codes
    assert "manual_price_liquidity_check_required" in codes
    assert not any(item.get("blocks_entry") for item in disclosures if item.get("code") == "advisory_only_no_auto_orders")


def test_v52_blocked_or_invalid_recommendation_adds_entry_blocking_disclosure() -> None:
    item = enrich_recommendation_row(
        base_row(
            operator_action="NO_TRADE",
            operator_hard_reasons=[{"code": "mtf_conflict", "title": "MTF veto", "detail": "older timeframe disagrees"}],
            last_price_time="2026-05-05T15:20:00+00:00",
            bar_time="2026-05-05T15:15:00+00:00",
            created_at="2026-05-05T15:16:00+00:00",
            expires_at="2026-05-05T16:15:00+00:00",
        ),
        now=NOW,
    )
    contract = item["recommendation"]
    blocking = [row for row in contract["operator_risk_disclosures"] if row.get("blocks_entry") is True]

    assert contract["trade_direction"] == "no_trade"
    assert contract["is_actionable"] is False
    assert "not_actionable_no_trade" in _codes(blocking)
    assert contract["contract_health"]["ok"] is True


def test_v52_no_trade_snapshot_has_operator_risk_disclosures_and_blocks_entry() -> None:
    snapshot = no_trade_decision_snapshot(reason="Недостаточно свежих данных", as_of=NOW)
    disclosures = snapshot["operator_risk_disclosures"]

    assert OPERATOR_RISK_DISCLOSURE_EXTENSION in snapshot["compatible_extensions"]
    assert snapshot["trade_direction"] == "no_trade"
    assert snapshot["is_actionable"] is False
    assert "advisory_only_no_auto_orders" in _codes(disclosures)
    assert "no_active_recommendation" in _codes(disclosures)
    assert any(item.get("blocks_entry") is True for item in disclosures)
    assert snapshot["contract_health"]["ok"] is True


def test_v52_api_metadata_and_summary_publish_risk_disclosure_extension() -> None:
    metadata = _recommendation_contract_metadata()
    summary = _recommendation_summary([])

    assert metadata["operator_risk_disclosure_extension"] == OPERATOR_RISK_DISCLOSURE_EXTENSION
    assert metadata["operator_risk_audit_view"] == "v_recommendation_integrity_audit_v52"
    assert OPERATOR_RISK_DISCLOSURE_EXTENSION in metadata["compatible_extensions"]
    assert OPERATOR_RISK_DISCLOSURE_EXTENSION in summary["compatible_extensions"]
    assert "operator_risk_disclosures" in metadata["required_recommendation_fields"]
    assert summary["risk_disclosure_extension"] == OPERATOR_RISK_DISCLOSURE_EXTENSION


def test_v52_sql_hardens_legacy_paper_trades_and_extends_integrity_audit() -> None:
    migration = (ROOT / "sql" / "migrations" / "20260505_v52_operator_risk_disclosure_and_paper_trade_integrity.sql").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")

    for source in (migration, schema):
        assert "ck_paper_trades_direction_v52" in source
        assert "ck_paper_trades_positive_numbers_v52" in source
        assert "ck_paper_trades_level_side_v52" in source
        assert "idx_paper_trades_advisory_audit_v52" in source
        assert "v_recommendation_integrity_audit_v52" in source
        assert "paper_trade_invalid_level_order_v52" in source
        assert "SELECT * FROM v_recommendation_integrity_audit_v51" in source


def test_v52_frontend_renders_server_owned_disclosures_without_recomputing_missing_contract() -> None:
    frontend = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    api_source = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert "function riskDisclosuresHtml" in frontend
    assert "contract.operator_risk_disclosures" in frontend
    assert "snapshot.operator_risk_disclosures" in frontend
    assert "function hasServerRecommendationContract" in frontend
    assert "server_contract_missing" in frontend
    assert "Фронт не получил серверный recommendation contract" in frontend
    assert ".risk-disclosure-list" in css
    assert ".risk-disclosure-item.critical" in css
    assert "v_recommendation_integrity_audit_v52" in api_source
    assert "OPERATOR_RISK_DISCLOSURE_EXTENSION" in api_source
