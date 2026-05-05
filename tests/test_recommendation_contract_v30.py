from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.trade_contract import enrich_recommendation_row, execution_plan, validate_trade_levels

ROOT = Path(__file__).resolve().parents[1]


def _row(**updates):
    row = {
        "id": 1001,
        "category": "linear",
        "symbol": "BTCUSDT",
        "interval": "15",
        "strategy": "trend_continuation_setup",
        "direction": "long",
        "confidence": 0.72,
        "entry": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "atr": 1.2,
        "bar_time": "2026-05-03T00:00:00+00:00",
        "expires_at": "2026-05-04T00:00:00+00:00",
        "operator_action": "REVIEW_ENTRY",
        "quality_status": "APPROVED",
        "rationale": {"reason": "unit_test"},
    }
    row.update(updates)
    return row


def test_position_sizing_is_backend_contract_not_frontend_math():
    levels = validate_trade_levels("long", 100, 98, 104)
    plan = execution_plan(levels)

    assert plan["risk_amount_usdt"] == settings.start_equity_usdt * settings.risk_per_trade
    assert plan["position_notional_usdt"] <= settings.max_position_notional_usdt
    assert plan["estimated_quantity"] > 0
    assert plan["fee_slippage_roundtrip_pct"] > 0
    assert plan["net_risk_reward"] < levels["risk_reward"]


def test_recommendation_contract_exposes_fee_adjusted_rr_and_position_sizing():
    item = enrich_recommendation_row(_row())
    contract = item["recommendation"]

    assert contract["position_sizing"]["risk_amount_usdt"] > 0
    assert contract["fee_slippage_roundtrip_pct"] > 0
    assert contract["net_risk_reward"] < contract["risk_reward"]
    assert contract["signal_breakdown"]["position_sizing"]["max_leverage"] == settings.max_leverage


def test_v30_schema_contains_operator_actions_and_numeric_hygiene():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260503_v30_recommendation_operator_actions_and_quality.sql").read_text(encoding="utf-8")

    for source in (schema, migration):
        assert "CREATE TABLE IF NOT EXISTS recommendation_operator_actions" in source
        assert "ck_signals_no_numeric_nan" in source
        assert "idx_signals_quality_segments_v30" in source
        assert "action IN ('skip','wait_confirmation','manual_review','close_invalidated','paper_opened')" in source


def test_api_exposes_operator_actions_and_quality_segments():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert '"/recommendations/{signal_id}/operator-action"' in api
    assert "class OperatorActionRequest" in api
    assert "_quality_segment_rows" in api
    assert '"by_confidence_bucket"' in api
    assert "recommendation_operator_actions" in api


def test_frontend_has_operator_action_buttons_and_displays_backend_sizing():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "async function postOperatorAction(action)" in js
    assert "function operatorActionPayload(action, candidate)" in js
    assert "function operatorActionButtonsHtml(contract)" in js
    assert "manual_review: 'Взять в разбор'" in js
    assert "wait_confirmation: 'Ждать подтверждения'" in js
    assert "close_invalidated: 'Закрыть как неактуальную'" in js
    assert "data-operator-action=\"${escapeHtml(item.action)}\"" in js
    assert "/api/recommendations/${encodeURIComponent(payload.signalId)}/operator-action" in js
    assert "state.lastOperatorAction" in js
    assert "position_sizing?.risk_amount_usdt" in js
    assert "position_sizing?.position_notional_usdt" in js
    assert "Net R/R" in js
    assert ".ticket-operator-actions" in css
