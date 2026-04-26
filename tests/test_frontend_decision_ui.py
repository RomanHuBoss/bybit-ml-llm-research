from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_has_decision_cockpit_structure():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    required_ids = [
        "decisionHero",
        "decisionStatus",
        "decisionTitle",
        "decisionScore",
        "tradePlan",
        "evidenceList",
        "guardrails",
        "candidateList",
        "briefBtn",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in html

    assert "Кандидаты для ручного решения" in html
    assert "Технические детали" in html
    assert "LIVE TRADING OFF" in html


def test_frontend_logic_contains_operator_risk_guards():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    required_fragments = [
        "function decisionFor",
        "function riskReward",
        "function guardrailItems",
        "function evidenceItems",
        "Не передавать оператору для входа",
        "Можно передать оператору на ручную проверку",
        "Система только рекомендует оператору",
    ]
    for fragment in required_fragments:
        assert fragment in js


def test_status_api_exposes_signal_age_for_ui():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert '"max_signal_age_hours": settings.max_signal_age_hours' in api
