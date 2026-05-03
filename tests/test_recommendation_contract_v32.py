from __future__ import annotations

from app.trade_contract import enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row


def test_v32_unknown_price_is_not_actionable_even_for_review_entry():
    item = enrich_recommendation_row(base_row(last_price=None, current_price=None, close=None))

    assert item["recommendation_status"] == "review_entry"
    assert item["price_status"] == "unknown"
    assert item["trade_direction"] == "long"
    assert item["is_actionable"] is False


def test_v32_outcome_evaluator_rechecks_open_outcomes(monkeypatch):
    import app.recommendation_outcomes as outcomes

    captured: dict[str, object] = {}

    def fake_fetch_all(query, params):
        captured["query"] = query
        captured["params"] = params
        return []

    monkeypatch.setattr(outcomes, "fetch_all", fake_fetch_all)

    rows = outcomes._due_signals("linear", 25)

    assert rows == []
    assert "o.outcome_status='open'" in str(captured["query"])
    assert captured["params"] == ("linear", 25)


def test_v32_frontend_defines_operator_action_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "async function postOperatorAction(action)" in js
    assert "function operatorActionPayload(action, candidate)" in js
    assert "observed_price" in js
    assert "ui_action=${action}" in js
    assert "manual_review: 'ручной разбор начат'" in js
