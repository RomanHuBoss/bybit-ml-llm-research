from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api import SignalBuildRequest, _market_state_for_recommendations
from app.trade_contract import enrich_recommendation_row
from tests.test_recommendation_contract_v28 import TEST_NOW, base_row

ROOT = Path(__file__).resolve().parents[1]


def test_v31_api_request_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        SignalBuildRequest(symbols=["BTCUSDT"], unexpected_frontend_field=True)


def test_v31_recommendation_contract_contains_operational_explanation_blocks():
    item = enrich_recommendation_row(
        base_row(
            rationale={
                "indicators": {"rsi": 31.5, "ema_fast": 101.0, "ema_slow": 99.0},
                "votes": [{"code": "rsi_rebound", "direction": "long", "timeframe": "15", "impact": 0.4, "detail": "RSI recovered from oversold."}],
                "timeframes_used": [{"interval": "15", "role": "entry", "status": "used"}],
            },
            trades_count=18,
            profit_factor=1.2,
            win_rate=0.52,
            max_drawdown=0.12,
        ),
        now=TEST_NOW,
    )
    contract = item["recommendation"]

    assert contract["statistics_confidence"]["level"] == "low"
    assert "18" in contract["statistics_confidence"]["explanation"]
    assert contract["timeframes_used"][0]["interval"] == "15"
    assert contract["indicator_values"]["rsi"] == 31.5
    assert contract["trading_signals"][0]["name"] == "rsi_rebound"
    assert contract["next_actions"][0]["action"] == "wait_confirmation"
    assert contract["price_actionability"]["reason"] == "price_unknown"


def test_v31_market_state_explains_no_trade_without_ui_guessing():
    state = _market_state_for_recommendations(payload_ok=True, recommendations=[])

    assert state["status"] == "no_trade"
    assert state["contract"] == "recommendation_v38"
    assert "NO_TRADE" in state["explanation"]


def test_v31_schema_and_migration_harden_risk_metrics_and_outcomes():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260503_v31_strict_recommendation_contract.sql").read_text(encoding="utf-8")

    for source in (schema, migration):
        assert "risk_pct NUMERIC GENERATED ALWAYS AS" in source
        assert "expected_reward_pct NUMERIC GENERATED ALWAYS AS" in source
        assert "risk_reward NUMERIC GENERATED ALWAYS AS" in source
        assert "ck_signals_generated_risk_metrics_v31" in source
        assert "ck_recommendation_outcome_terminal_fields_v31" in source
        assert "enforce_signal_recommendation_contract_v31" in source
        assert "invalid LONG levels" in source
        assert "invalid SHORT levels" in source
        assert "v_recommendation_quality_summary" in source


def test_v31_frontend_uses_recommendation_endpoint_and_detail_blocks():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    for fragment in [
        "/api/recommendations/active",
        "state.marketState",
        "Почему появилось",
        "Что против сделки",
        "Выборка качества",
        "indicatorValuesHtml",
        "nextActionsHtml",
    ]:
        assert fragment in js
    for fragment in [".recommendation-detail-grid", ".detail-card", ".indicator-chip"]:
        assert fragment in css
