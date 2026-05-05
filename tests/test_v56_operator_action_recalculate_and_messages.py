from __future__ import annotations

from pathlib import Path

import app.api as api

ROOT = Path(__file__).resolve().parents[1]


def _contract(**updates):
    base = {
        "recommendation_status": "review_entry",
        "trade_direction": "long",
        "is_actionable": True,
        "price_status": "entry_zone",
        "last_price": 100.25,
        "contract_health": {"ok": True, "problems": []},
        "price_actionability": {"is_price_actionable": True, "price_status": "entry_zone"},
        "operator_checklist": [{"key": "price_gate", "status": "pass"}],
        "primary_next_action": {"action": "paper_opened", "label": "paper"},
        "next_actions": [{"action": "paper_opened", "label": "paper"}],
    }
    base.update(updates)
    return base


def test_v56_rejected_paper_action_returns_operator_friendly_gate(monkeypatch):
    monkeypatch.setattr(api, "_fetch_recommendation_row", lambda *_args, **_kwargs: {"id": 501, "category": "linear"})
    monkeypatch.setattr(
        api,
        "annotate_recommendations",
        lambda rows: [{**rows[0], "recommendation": _contract(recommendation_status="wait", is_actionable=False, price_status="unknown")}],
    )
    calls = []
    monkeypatch.setattr(api, "execute", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = api.api_recommendation_operator_action(501, api.OperatorActionRequest(action="paper_opened"), category="linear")

    assert result["ok"] is False
    assert result["status"] == "rejected_by_server_gate"
    assert result["operator_action_gate"]["allowed"] is False
    assert result["operator_action_gate"]["recommendation_status"] == "wait"
    assert "Paper-вход отклонен сервером" in result["user_message"]
    assert "текущий статус рекомендации wait" in result["user_message"]
    assert calls == []


def test_v56_successful_paper_action_exposes_public_gate(monkeypatch):
    monkeypatch.setattr(api, "_fetch_recommendation_row", lambda *_args, **_kwargs: {"id": 502, "category": "linear"})
    monkeypatch.setattr(api, "annotate_recommendations", lambda rows: [{**rows[0], "recommendation": _contract()}])
    calls = []
    monkeypatch.setattr(api, "execute", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = api.api_recommendation_operator_action(502, api.OperatorActionRequest(action="paper_opened"), category="linear")

    assert result["ok"] is True
    assert result["operator_action_gate"]["allowed"] is True
    assert result["operator_action_gate"]["price_gate_ok"] is True
    assert result["operator_action_gate"]["primary_next_action"]["action"] == "paper_opened"
    assert calls


def test_v56_frontend_blocks_stale_paper_action_before_api_and_supports_recalculate_button():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function paperGateState(contract)" in js
    assert "operatorActionBlockedReason(action, contract)" in js
    assert "if (blockedReason) throw new Error(blockedReason);" in js
    assert "recalculate: 'Пересчитать'" in js
    assert "async function recalculateRecommendationsFromCurrentSelection()" in js
    assert "/api/recommendations/recalculate" in js
    assert "action === 'recalculate'" in js
