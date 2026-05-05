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
        "risk_reward": 2.0,
        "net_risk_reward": 1.82,
        "expires_at": "2026-05-05T12:00:00+00:00",
        "market_freshness": {"status": "fresh"},
        "contract_health": {"ok": True, "problems": []},
        "operator_checklist": [
            {"key": "price_gate", "status": "pass", "title": "Price gate", "text": "entry zone"},
        ],
    }
    base.update(updates)
    return base


def test_v51_api_rejects_paper_opened_when_contract_is_not_actionable(monkeypatch):
    monkeypatch.setattr(api, "_fetch_recommendation_row", lambda *_args, **_kwargs: {"id": 101, "category": "linear"})
    monkeypatch.setattr(
        api,
        "annotate_recommendations",
        lambda rows: [{**rows[0], "recommendation": _contract(recommendation_status="missed_entry", is_actionable=False, price_status="moved_away")}],
    )
    calls = []
    monkeypatch.setattr(api, "execute", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = api.api_recommendation_operator_action(101, api.OperatorActionRequest(action="paper_opened"), category="linear")

    assert result["ok"] is False
    assert result["status"] == "rejected_by_server_gate"
    assert "review_entry" in result["error"]
    assert calls == []


def test_v51_api_accepts_paper_opened_only_with_server_gate_and_audit_price(monkeypatch):
    monkeypatch.setattr(api, "_fetch_recommendation_row", lambda *_args, **_kwargs: {"id": 102, "category": "linear"})
    monkeypatch.setattr(api, "annotate_recommendations", lambda rows: [{**rows[0], "recommendation": _contract()}])
    calls = []
    monkeypatch.setattr(api, "execute", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = api.api_recommendation_operator_action(102, api.OperatorActionRequest(action="paper_opened"), category="linear")

    assert result["ok"] is True
    assert result["status"] == "paper_opened"
    assert calls, "paper action must be persisted after server gate passes"
    params = calls[0][0][1]
    assert params[1] == "paper_opened"
    assert params[3] == 100.25
    assert params[5]["is_actionable"] is True
    assert params[5]["contract_health_ok"] is True
    assert params[5]["price_status"] == "entry_zone"


def test_v51_sql_and_metadata_expose_operator_action_gate():
    migration = (ROOT / "sql" / "migrations" / "20260505_v51_operator_action_server_gate.sql").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    api_source = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
    trade_contract = (ROOT / "app" / "trade_contract.py").read_text(encoding="utf-8")

    for source in (migration, schema):
        assert "ck_recommendation_operator_actions_paper_price_v51" in source
        assert "ck_recommendation_operator_actions_paper_status_v51" in source
        assert "v_recommendation_integrity_audit_v51" in source
    assert "operator_action_server_gate_v51" in trade_contract
    assert '"operator_action_audit_view": "v_recommendation_integrity_audit_v51"' in api_source
    assert '"v_recommendation_integrity_audit_v51", "v_recommendation_integrity_audit_v48"' in api_source


def test_v51_frontend_keeps_manual_review_available_but_marks_paper_gate_as_server_checked():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'data-operator-action="manual_review">Взять в разбор</button>' in js
    assert "API повторно проверит это на сервере" in js
    assert "paper-вход дополнительно проходит V51 server gate" in js
