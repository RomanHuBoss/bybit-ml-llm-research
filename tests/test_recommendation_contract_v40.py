from __future__ import annotations

from pathlib import Path

from app.operator_queue import consolidate_operator_queue
from app.recommendation import annotate_recommendations, ensure_operator_decisions
from app.trade_contract import RECOMMENDATION_CONTRACT_VERSION
from tests.test_operator_queue_stability import row

ROOT = Path(__file__).resolve().parents[1]


def test_v40_consolidation_happens_before_contract_enrichment_for_direction_conflict():
    rows = [
        row(id=401, direction="long", strategy="ema_pullback_trend", confidence=0.66, research_score=0.50),
        row(id=402, direction="short", strategy="funding_extreme_contrarian", confidence=0.65, research_score=0.50, stop_loss=102.0, take_profit=96.0),
    ]

    queue = annotate_recommendations(consolidate_operator_queue(ensure_operator_decisions(rows), limit=10))

    assert len(queue) == 1
    item = queue[0]
    contract = item["recommendation"]
    assert item["operator_action"] == "NO_TRADE"
    assert item["direction_conflict"] is True
    assert contract["recommendation_status"] == "blocked"
    assert contract["trade_direction"] == "no_trade"
    assert contract["display_direction"] == "NO_TRADE"
    assert contract["is_actionable"] is False
    assert any(reason["code"] == "direction_conflict" for reason in contract["factors_against"])


def test_v40_runtime_and_schema_publish_single_server_owned_contract_version():
    assert RECOMMENDATION_CONTRACT_VERSION == "recommendation_v40"
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260504_v40_operator_queue_contract_consistency.sql").read_text(encoding="utf-8")

    assert "ensure_operator_decisions(rows)" in api
    assert "server_enriched_contract_v40" in api
    assert "Frontend v40" in frontend
    assert "v_recommendation_integrity_audit_v40" in migration
    assert "operator_contract_conflict_mismatch" in migration
