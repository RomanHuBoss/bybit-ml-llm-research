from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.recommendation import classify_operator_action
from app.trade_contract import enrich_recommendation_row, no_trade_decision_snapshot
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc)


def test_v37_extended_price_is_demoted_to_missed_entry_no_trade():
    item = enrich_recommendation_row(
        base_row(
            entry=100,
            stop_loss=96,
            take_profit=108,
            last_price=100.6,
            atr=1,
            bar_time="2026-05-04T07:45:00+00:00",
            expires_at="2026-05-04T09:00:00+00:00",
            operator_action="REVIEW_ENTRY",
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert contract["contract_version"] == "recommendation_v40"
    assert contract["recommendation_status"] == "missed_entry"
    assert contract["trade_direction"] == "no_trade"
    assert contract["price_status"] == "extended"
    assert contract["price_actionability"]["is_price_actionable"] is False
    assert contract["price_actionability"]["reason"] == "price_extended_wait_retest"
    assert contract["is_actionable"] is False
    assert contract["no_trade_reason"] == "price_extended_wait_retest"
    assert contract["next_actions"][0]["action"] == "wait_confirmation"
    assert contract["contract_health"]["ok"] is True


def test_v37_net_rr_gate_blocks_fee_adjusted_bad_review_candidate():
    verdict = classify_operator_action(
        base_row(
            entry=100.0,
            stop_loss=99.9,
            take_profit=100.12,
            atr=0.1,
            confidence=0.7,
            mtf_status="aligned",
            is_eligible=True,
            spread_pct=0.001,
            quality_status="APPROVED",
            quality_score=95,
            trades_count=80,
            profit_factor=1.6,
            win_rate=0.55,
            max_drawdown=0.08,
            walk_forward_pass_rate=0.7,
            walk_forward_windows=4,
        )
    )

    assert verdict["operator_action"] == "NO_TRADE"
    assert any(reason["code"] == "net_rr_low" for reason in verdict["operator_hard_reasons"])


def test_v37_no_trade_snapshot_also_carries_contract_health():
    snap = no_trade_decision_snapshot(reason="Нет активных рекомендаций", category="linear", as_of=NOW)

    assert snap["contract_version"] == "recommendation_v40"
    assert snap["contract_health"]["ok"] is True
    assert snap["price_actionability"]["reason"] == "no_active_recommendation"


def test_v37_schema_migration_and_frontend_publish_guardrails():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260504_v37_contract_guardrails_and_integrity_audit.sql").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    for source in (schema, migration):
        assert "v_recommendation_integrity_audit_v37" in source
        assert "v_recommendation_contract_v37" in source
        assert "recommendation_v37" in source
        assert "ck_signals_rationale_json_object_v37" in source
    assert "contractHealthHtml" in js
    assert 'data-operator-action="manual_review">Взять в разбор</button>' in js
    assert "Paper-отметка доступна только" in js
    assert ".contract-health" in css
