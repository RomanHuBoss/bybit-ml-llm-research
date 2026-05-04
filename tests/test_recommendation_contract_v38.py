from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.trade_contract import RECOMMENDATION_CONTRACT_VERSION, enrich_recommendation_row, no_trade_decision_snapshot
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc)


def test_v38_contract_declares_server_only_decision_source():
    item = enrich_recommendation_row(
        base_row(
            entry=100,
            stop_loss=96,
            take_profit=108,
            last_price=100.05,
            atr=1,
            bar_time="2026-05-04T09:45:00+00:00",
            expires_at="2026-05-04T11:00:00+00:00",
            operator_action="REVIEW_ENTRY",
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert RECOMMENDATION_CONTRACT_VERSION == "recommendation_v38"
    assert contract["contract_version"] == "recommendation_v38"
    assert contract["decision_source"] == "server_enriched_contract_v38"
    assert contract["frontend_may_recalculate"] is False
    assert contract["contract_health"]["ok"] is True


def test_v38_no_trade_snapshot_is_also_server_only():
    snap = no_trade_decision_snapshot(reason="Нет активных рекомендаций", category="linear", as_of=NOW)

    assert snap["contract_version"] == "recommendation_v38"
    assert snap["decision_source"] == "server_enriched_contract_v38"
    assert snap["frontend_may_recalculate"] is False
    assert snap["contract_health"]["ok"] is True


def test_v38_frontend_does_not_recompute_trade_math_or_decision():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "legacy_fallback" not in js
    assert "reward / risk" not in js
    assert "Math.abs(entry - stop)" not in js
    assert "Frontend v38 не пересчитывает торговое решение" in js
    assert "frontend не\n  // пересчитывает торговое решение" in js
    assert "contract.risk_reward ??" not in js
    assert "riskReward(s)?.ratio" in js  # allowed: riskReward now returns server fields only.


def test_v38_schema_migration_publishes_server_only_contract_and_integrity_audit():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260504_v38_server_only_recommendation_contract.sql").read_text(encoding="utf-8")
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    for source in (schema, migration):
        assert "enforce_signal_recommendation_contract_v38" in source
        assert "v_recommendation_integrity_audit_v38" in source
        assert "v_recommendation_contract_v38" in source
        assert "recommendation_v38" in source
        assert "active_direction_conflict" in source
        assert "missing_explanation_payload" in source
        assert "missing_timeframe_context" in source
        assert "ck_signals_directional_ttl_upper_bound_v38" in source
    assert "FROM v_recommendation_integrity_audit_v38" in api
    assert '"frontend_may_recalculate": False' in api
