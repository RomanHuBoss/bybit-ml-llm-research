from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.trade_contract import enrich_recommendation_row, no_trade_decision_snapshot
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)


def test_v36_price_actionability_blocks_moved_away_price():
    item = enrich_recommendation_row(
        base_row(
            direction="long",
            entry=100,
            stop_loss=96,
            take_profit=108,
            last_price=112,
            atr=1,
            bar_time="2026-05-03T07:45:00+00:00",
            expires_at="2026-05-03T09:00:00+00:00",
            operator_action="REVIEW_ENTRY",
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert contract["contract_version"] == "recommendation_v36"
    assert contract["recommendation_status"] == "missed_entry"
    assert contract["trade_direction"] == "no_trade"
    assert contract["price_actionability"]["is_price_actionable"] is False
    assert contract["price_actionability"]["reason"] == "price_moved_away"
    assert contract["is_actionable"] is False


def test_v36_price_actionability_allows_fresh_review_entry_inside_entry_window():
    item = enrich_recommendation_row(
        base_row(
            direction="short",
            entry=100,
            stop_loss=104,
            take_profit=92,
            last_price=99.9,
            atr=1,
            bar_time="2026-05-03T07:45:00+00:00",
            expires_at="2026-05-03T09:00:00+00:00",
            operator_action="REVIEW_ENTRY",
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert contract["recommendation_status"] == "review_entry"
    assert contract["trade_direction"] == "short"
    assert contract["price_actionability"]["status"] == "actionable"
    assert contract["price_actionability"]["is_price_actionable"] is True
    assert contract["entry_window"]["low"] < 100 < contract["entry_window"]["high"]
    assert contract["risk_reward"] == 2.0
    assert contract["confidence_semantics"] == "engineering_score_not_win_probability"


def test_v36_no_trade_snapshot_contains_price_gate():
    snap = no_trade_decision_snapshot(reason="Нет активных рекомендаций", category="linear", as_of=NOW)

    assert snap["contract_version"] == "recommendation_v36"
    assert snap["trade_direction"] == "no_trade"
    assert snap["price_actionability"]["status"] == "blocked"
    assert snap["price_actionability"]["reason"] == "no_active_recommendation"
    assert snap["entry_window"] is None
    assert snap["is_actionable"] is False


def test_v36_api_publishes_contract_metadata_before_dynamic_detail_route():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert "def api_recommendation_contract" in api
    assert '"frontend_source_of_truth": "recommendations_active"' in api
    assert api.index('@router.get("/recommendations/contract")') < api.index('@router.get("/recommendations/{signal_id}")')


def test_v36_frontend_uses_active_recommendations_before_rank_fallback():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "function activeRecommendationSource" in js
    assert "return state.signals.length ? state.signals.map(enrichedSignal) : state.rank.map(withLlmFields);" in js
    assert "source: 'server_contract'" in js
    assert "contract.risk_reward" in js
    assert "price_actionability" in js
    assert "const source = state.rank.length ? state.rank.map(withLlmFields)" not in js
    assert ".price-actionability" in css


def test_v36_schema_and_migration_publish_contract_view():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260503_v36_frontend_contract_source_and_price_actionability.sql").read_text(encoding="utf-8")

    for source in (schema, migration):
        assert "v_recommendation_contract_v36" in source
        assert "recommendation_v36" in source
        assert "idx_signals_active_source_v36" in source
        assert "recommendations_active" in source
