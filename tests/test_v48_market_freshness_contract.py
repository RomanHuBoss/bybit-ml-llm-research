from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.api import _recommendation_contract_metadata, _recommendation_summary
from app.trade_contract import MARKET_FRESHNESS_EXTENSION, enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 5, 15, 0, tzinfo=timezone.utc)


def test_v48_stale_reference_price_blocks_review_entry_even_when_ttl_active() -> None:
    item = enrich_recommendation_row(
        base_row(
            operator_action="REVIEW_ENTRY",
            entry=100.0,
            stop_loss=97.0,
            take_profit=106.0,
            last_price=100.01,
            last_price_time="2026-05-05T13:55:00+00:00",
            bar_time="2026-05-05T14:45:00+00:00",
            created_at="2026-05-05T14:46:00+00:00",
            expires_at="2026-05-05T16:00:00+00:00",
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert MARKET_FRESHNESS_EXTENSION in contract["compatible_extensions"]
    assert contract["ttl_status"] == "active"
    assert contract["price_status"] == "stale"
    assert contract["recommendation_status"] == "expired"
    assert contract["trade_direction"] == "no_trade"
    assert contract["is_actionable"] is False
    assert contract["market_freshness"]["status"] == "stale"
    assert contract["market_freshness"]["reason"] == "price_timestamp_too_old"
    assert contract["price_actionability"]["reason"] == "price_timestamp_too_old"
    freshness_checks = [row for row in contract["operator_checklist"] if row["key"] == "market_freshness"]
    assert freshness_checks and freshness_checks[0]["status"] == "fail"


def test_v48_fresh_reference_price_keeps_review_entry_actionable() -> None:
    item = enrich_recommendation_row(
        base_row(
            operator_action="REVIEW_ENTRY",
            entry=100.0,
            stop_loss=97.0,
            take_profit=106.0,
            last_price=100.01,
            last_price_time="2026-05-05T14:48:00+00:00",
            bar_time="2026-05-05T14:45:00+00:00",
            created_at="2026-05-05T14:46:00+00:00",
            expires_at="2026-05-05T16:00:00+00:00",
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert contract["market_freshness"]["status"] == "fresh"
    assert contract["last_price_age_seconds"] == 12 * 60
    assert contract["recommendation_status"] == "review_entry"
    assert contract["price_actionability"]["is_price_actionable"] is True
    assert contract["contract_health"]["ok"] is True


def test_v48_metadata_sql_and_frontend_publish_market_price_freshness_guard() -> None:
    metadata = _recommendation_contract_metadata()
    summary = _recommendation_summary([])
    migration = (ROOT / "sql" / "migrations" / "20260505_v48_market_price_freshness_contract.sql").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert metadata["market_freshness_extension"] == MARKET_FRESHNESS_EXTENSION
    assert metadata["market_freshness_audit_view"] == "v_recommendation_integrity_audit_v48"
    assert MARKET_FRESHNESS_EXTENSION in metadata["compatible_extensions"]
    assert MARKET_FRESHNESS_EXTENSION in summary["compatible_extensions"]
    assert "market_freshness" in metadata["required_recommendation_fields"]
    for source in (migration, schema):
        assert "v_recommendation_integrity_audit_v48" in source
        assert "v_recommendation_contract_v48" in source
        assert "active_reference_price_stale_v48" in source
        assert MARKET_FRESHNESS_EXTENSION in source
    assert "marketFreshnessText" in frontend
    assert "Market freshness" in frontend
    assert '"v_recommendation_integrity_audit_v48"' in api
