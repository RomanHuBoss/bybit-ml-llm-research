from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.api import _recommendation_contract_metadata, _recommendation_summary
from app.recommendation import classify_operator_action
from app.trade_contract import MARKET_CONTEXT_GUARD_EXTENSION, enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 5, 15, 0, tzinfo=timezone.utc)


def row_with_context(**overrides):
    base = dict(
        category="linear",
        operator_action="REVIEW_ENTRY",
        operator_quality_mode="provisional",
        entry=100.0,
        stop_loss=97.0,
        take_profit=106.0,
        atr=1.0,
        last_price=100.01,
        last_price_time="2026-05-05T14:48:00+00:00",
        bar_time="2026-05-05T14:45:00+00:00",
        created_at="2026-05-05T14:46:00+00:00",
        expires_at="2026-05-05T16:00:00+00:00",
        spread_pct=0.01,
        turnover_24h=50_000_000.0,
        open_interest_value=30_000_000.0,
        funding_rate=0.0001,
        rationale={"volume_zscore": 0.8, "votes": [{"name": "ema", "direction": "long", "impact": "positive"}]},
    )
    base.update(overrides)
    return base_row(**base)


def test_v53_market_context_is_published_without_blocking_when_only_optional_context_missing() -> None:
    item = enrich_recommendation_row(
        base_row(
            category="linear",
            operator_action="REVIEW_ENTRY",
            operator_quality_mode="provisional",
            entry=100.0,
            stop_loss=97.0,
            take_profit=106.0,
            atr=1.0,
            last_price=100.01,
            last_price_time="2026-05-05T14:48:00+00:00",
            bar_time="2026-05-05T14:45:00+00:00",
            created_at="2026-05-05T14:46:00+00:00",
            expires_at="2026-05-05T16:00:00+00:00",
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert MARKET_CONTEXT_GUARD_EXTENSION in contract["compatible_extensions"]
    assert contract["market_context_guardrails"]["extension"] == MARKET_CONTEXT_GUARD_EXTENSION
    assert contract["market_context_guardrails"]["status"] == "warn"
    assert contract["market_context_guardrails"]["blocks_entry"] is False
    assert contract["recommendation_status"] == "review_entry"
    assert any(row["key"] == "market_context" for row in contract["operator_checklist"])
    assert contract["signal_breakdown"]["market_context"]["extension"] == MARKET_CONTEXT_GUARD_EXTENSION
    assert contract["contract_health"]["ok"] is True


def test_v53_extreme_volatility_or_position_risk_demotes_review_entry_to_no_trade() -> None:
    item = enrich_recommendation_row(
        row_with_context(stop_loss=80.0, take_profit=140.0, atr=20.0),
        now=NOW,
    )
    contract = item["recommendation"]

    assert contract["market_context_guardrails"]["blocks_entry"] is True
    assert contract["recommendation_status"] == "blocked"
    assert contract["trade_direction"] == "no_trade"
    assert contract["is_actionable"] is False
    assert any(d["code"] == "market_context_blocks_entry" for d in contract["operator_risk_disclosures"])
    assert contract["contract_health"]["ok"] is True


def test_v53_funding_hard_veto_blocks_directional_entry() -> None:
    item = enrich_recommendation_row(row_with_context(funding_rate=0.004), now=NOW)
    contract = item["recommendation"]

    assert contract["market_context_guardrails"]["blocks_entry"] is True
    assert contract["recommendation_status"] == "blocked"
    assert any(i["key"] == "funding" and i["status"] == "fail" for i in contract["market_context_guardrails"]["items"])


def test_v53_classifier_rejects_confidence_outside_zero_one_even_before_db_constraints() -> None:
    decision = classify_operator_action(row_with_context(confidence=1.25))

    assert decision["operator_action"] == "NO_TRADE"
    assert any(reason["code"] == "confidence_range" for reason in decision["operator_hard_reasons"])


def test_v53_metadata_frontend_and_sql_publish_market_context_contract() -> None:
    metadata = _recommendation_contract_metadata()
    summary = _recommendation_summary([])
    frontend = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260505_v53_market_context_guardrails.sql").read_text(encoding="utf-8")

    assert metadata["market_context_extension"] == MARKET_CONTEXT_GUARD_EXTENSION
    assert metadata["market_context_audit_view"] == "v_recommendation_market_context_audit_v53"
    assert summary["market_context_extension"] == MARKET_CONTEXT_GUARD_EXTENSION
    assert "market_context_guardrails" in metadata["required_recommendation_fields"]
    assert "function marketContextHtml" in frontend
    assert "contract.market_context_guardrails" in frontend
    assert ".market-context-grid" in css
    for source in (schema, migration):
        assert "ck_signals_no_numeric_infinity_v53" in source
        assert "v_recommendation_market_context_audit_v53" in source
        assert "confidence_out_of_range_v53" in source
        assert "extreme_atr_distance_v53" in source
