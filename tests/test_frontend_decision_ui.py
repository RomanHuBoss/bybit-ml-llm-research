from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_has_operator_workstation_structure():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    required_ids = [
        "decisionBoard",
        "decisionBadge",
        "decisionTitle",
        "decisionScore",
        "ticketBody",
        "checklist",
        "reasonList",
        "operatorProtocol",
        "candidateQueue",
        "briefBtn",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in html

    assert "Рабочее место оператора" in html
    assert "Красный пункт = отмена" in html
    assert "Технические детали и журнал" in html
    assert "LIVE OFF" in html


def test_frontend_keeps_technical_data_secondary():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert '<details class="panel technical-details">' in html
    assert '<details class="ops-drawer">' in html
    assert "Операции с данными" in html


def test_frontend_logic_contains_operator_trade_guards():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    required_fragments = [
        "function checklistFor",
        "function decisionFor",
        "function riskReward",
        "function operatorProtocol",
        "Красных пунктов",
        "НЕТ ВХОДА",
        "К ПРОВЕРКЕ",
        "не создает бота автоматически",
    ]
    for fragment in required_fragments:
        assert fragment in js


def test_status_api_exposes_signal_age_for_ui():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert '"max_signal_age_hours": settings.max_signal_age_hours' in api
